#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
OUTBOX = LOG_DIR / "telegram_report_outbox.jsonl"
NY_TZ = ZoneInfo("America/New_York")

REMOTEAGENT_REPORT_BIN = os.environ.get(
    "REMOTEAGENT_REPORT_BIN",
    "/home/ospadmin/.remoteagent/app/remoteagent-src/dist/report-telegram.js",
)
REMOTEAGENT_PUBLIC_SESSION_ID = os.environ.get("REMOTEAGENT_PUBLIC_SESSION_ID", "S002")


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


def _send_remoteagent(text: str) -> None:
    report_bin = Path(REMOTEAGENT_REPORT_BIN)
    if not report_bin.exists() or not REMOTEAGENT_PUBLIC_SESSION_ID:
        return
    subprocess.run(
        ["node", str(report_bin), "--session", REMOTEAGENT_PUBLIC_SESSION_ID, text],
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
