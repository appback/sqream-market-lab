#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import subprocess
import traceback
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
STATE_DIR = BASE_DIR / "state"
OUTBOX = LOG_DIR / "telegram_report_outbox.jsonl"
DELIVERY_LOG = LOG_DIR / "report_notifier_delivery.jsonl"
REPORTBOT_CHAT_ID_CACHE = STATE_DIR / "reportbot_chat_id.txt"
NY_TZ = ZoneInfo("America/New_York")

REMOTEAGENT_REPORT_BIN = os.environ.get(
    "REMOTEAGENT_REPORT_BIN",
    "/home/ospadmin/.remoteagent/app/remoteagent-src/dist/report-telegram.js",
)
REMOTEAGENT_PUBLIC_SESSION_ID = os.environ.get("REMOTEAGENT_PUBLIC_SESSION_ID", "S002")
REMOTEAGENT_SECRET_BIN_CANDIDATES = (
    os.environ.get("REMOTEAGENT_SECRET_BIN", ""),
    "/home/ospadmin/.remoteagent/app/remoteagent-src/dist/secret-helper.js",
    "/home/ospadmin/.nvm/versions/node/v20.20.2/lib/node_modules/appback-remoteagent/dist/secret-helper.js",
)
NODE_BIN_CANDIDATES = (
    os.environ.get("NODE_BIN", ""),
    "/home/ospadmin/.nvm/versions/node/v20.20.2/bin/node",
    shutil.which("node") or "",
    "/usr/bin/node",
)


PersistReport = Callable[[str, str, str], None]


def _append_outbox(created_at: str, event_type: str, text: str, payload: dict | None) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    row = {
        "created_at": created_at,
        "event_type": event_type,
        "text": text,
        "payload": payload or {},
    }
    with OUTBOX.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_delivery(event_type: str, payload: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    row = {
        "created_at": datetime.now(NY_TZ).isoformat(),
        "event_type": event_type,
        "payload": payload,
    }
    with DELIVERY_LOG.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _get_secret(key: str) -> str:
    node_bin = next((candidate for candidate in NODE_BIN_CANDIDATES if candidate and Path(candidate).exists()), "")
    if not node_bin:
        _append_delivery("secret_lookup_failed", {"key": key, "reason": "node binary missing"})
        return ""

    for candidate in REMOTEAGENT_SECRET_BIN_CANDIDATES:
        if not candidate:
            continue
        secret_bin = Path(candidate)
        if not secret_bin.exists():
            continue
        result = subprocess.run(
            [node_bin, str(secret_bin), "get", key],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        if result.returncode != 0:
            _append_delivery(
                "secret_lookup_failed",
                {
                    "key": key,
                    "secret_bin": str(secret_bin),
                    "returncode": result.returncode,
                    "stderr": result.stderr.strip().splitlines()[-1:] or [],
                },
            )
    return ""


def _resolve_reportbot_token() -> str:
    return os.environ.get("REPORTBOT_TOKEN", "").strip() or _get_secret("REPORTBOT_TOKEN")


def _cache_reportbot_chat_id(chat_id: str) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    REPORTBOT_CHAT_ID_CACHE.write_text(chat_id.strip() + "\n")


def _resolve_reportbot_chat_id(token: str) -> str:
    env_chat_id = os.environ.get("REPORTBOT_CHAT_ID", "").strip()
    if env_chat_id:
        _cache_reportbot_chat_id(env_chat_id)
        return env_chat_id

    secret_chat_id = _get_secret("REPORTBOT_CHAT_ID").strip()
    if secret_chat_id:
        _cache_reportbot_chat_id(secret_chat_id)
        return secret_chat_id

    if REPORTBOT_CHAT_ID_CACHE.exists():
        cached = REPORTBOT_CHAT_ID_CACHE.read_text().strip()
        if cached:
            return cached

    if not token:
        return ""

    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/getUpdates",
            timeout=10,
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        _append_delivery("reportbot_chat_id_discovery_failed", {"error": str(exc)})
        return ""

    for item in reversed(data.get("result", [])):
        message = item.get("message") or item.get("channel_post") or item.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is not None:
            resolved = str(chat_id)
            _cache_reportbot_chat_id(resolved)
            return resolved
    return ""


def _send_reportbot(text: str) -> None:
    token = _resolve_reportbot_token()
    if not token:
        _append_delivery("reportbot_skipped", {"reason": "REPORTBOT_TOKEN missing"})
        return

    chat_id = _resolve_reportbot_chat_id(token)
    if not chat_id:
        _append_delivery(
            "reportbot_skipped",
            {"reason": "REPORTBOT_CHAT_ID missing and getUpdates returned no chat"},
        )
        return

    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        _append_delivery("reportbot_send_failed", {"error": str(exc)})
        return

    result = body.get("result") or {}
    chat = result.get("chat") or {}
    _append_delivery(
        "reportbot_send_ok" if body.get("ok") else "reportbot_send_failed",
        {
            "ok": bool(body.get("ok")),
            "message_id": result.get("message_id"),
            "chat_id": chat.get("id"),
        },
    )


def _send_remoteagent(text: str) -> None:
    report_bin = Path(REMOTEAGENT_REPORT_BIN)
    if not report_bin.exists() or not REMOTEAGENT_PUBLIC_SESSION_ID:
        return
    node_bin = next((candidate for candidate in NODE_BIN_CANDIDATES if candidate and Path(candidate).exists()), "")
    if not node_bin:
        return
    subprocess.run(
        [node_bin, str(report_bin), "--session", REMOTEAGENT_PUBLIC_SESSION_ID, text],
        capture_output=True,
        text=True,
        check=False,
    )


def notify(
    event_type: str,
    text: str,
    payload: dict | None = None,
    *,
    persist_report: PersistReport | None = None,
    print_text: bool = True,
) -> None:
    created_at = datetime.now(NY_TZ).isoformat()
    _append_outbox(created_at, event_type, text, payload)
    if persist_report is not None:
        try:
            persist_report(created_at, event_type, text)
        except Exception as exc:
            _append_outbox(
                created_at,
                "보고 저장 실패",
                f"[보고 저장 실패] event_type={event_type} error={exc}",
                {"source_event_type": event_type, "error": str(exc)},
            )
    _send_reportbot(text)
    _send_remoteagent(text)
    if print_text:
        print(text)


def notify_error(
    context: str,
    exc: BaseException,
    payload: dict | None = None,
    *,
    persist_report: PersistReport | None = None,
) -> None:
    error_text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    notify(
        "장중 에러",
        f"[장중 에러] context={context} error={error_text}",
        {
            "context": context,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=20),
            **(payload or {}),
        },
        persist_report=persist_report,
    )
