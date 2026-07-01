#!/usr/bin/env python3

from __future__ import annotations

import argparse
import html
import json
import os
import urllib.parse
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
LEDGER_PATH = BASE_DIR / "state" / "paper_trade_ledger.jsonl"
STRATEGY_PATH = BASE_DIR / "docs" / "strategy_versions.json"
ACTIVE_STATUSES = {"active_paper", "candidate"}
D1_ALGORITHM_NAME = "d1_vol5_absret10_breakout_2_target10_stop5_eod"
D1_OPENING_START = (9, 30, 0)
D1_OPENING_END = (10, 15, 0)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def read_strategies() -> list[dict[str, Any]]:
    if not STRATEGY_PATH.exists():
        return []
    return json.loads(STRATEGY_PATH.read_text(encoding="utf-8"))


def write_strategies(rows: list[dict[str, Any]]) -> None:
    STRATEGY_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def recent_rows(rows: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    dates = sorted({row.get("trade_date") for row in rows if row.get("trade_date")}, reverse=True)[:days]
    date_set = set(dates)
    return [row for row in rows if row.get("trade_date") in date_set]


def opened_time_tuple(row: dict[str, Any]) -> tuple[int, int, int] | None:
    opened_at = str(row.get("opened_at") or "")
    if "T" not in opened_at:
        return None
    time_part = opened_at.split("T", 1)[1].split("-", 1)[0].split("+", 1)[0]
    try:
        hour, minute, second = [int(part) for part in time_part.split(":")[:3]]
    except (TypeError, ValueError):
        return None
    return hour, minute, second


def d1_current_policy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if row.get("algorithm") != D1_ALGORITHM_NAME:
            continue
        opened_time = opened_time_tuple(row)
        if opened_time is None:
            continue
        if D1_OPENING_START <= opened_time < D1_OPENING_END:
            result.append(row)
    return result


def d1_excluded_by_policy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if row.get("algorithm") != D1_ALGORITHM_NAME:
            continue
        opened_time = opened_time_tuple(row)
        if opened_time is None or not (D1_OPENING_START <= opened_time < D1_OPENING_END):
            result.append(row)
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(row.get("pnl_pct") or 0.0) for row in rows]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(pnls) * 100.0) if pnls else 0.0,
        "avg_pnl": (sum(pnls) / len(pnls)) if pnls else 0.0,
        "total_pnl": sum(pnls),
        "best": max(pnls) if pnls else 0.0,
        "worst": min(pnls) if pnls else 0.0,
    }


def group_by_strategy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("algorithm") or "unknown")].append(row)
    result = []
    for strategy, strategy_rows in grouped.items():
        summary = summarize(strategy_rows)
        summary["strategy_name"] = strategy
        result.append(summary)
    return sorted(result, key=lambda row: (row["total_pnl"], row["trades"]), reverse=True)


def active_strategy_names(strategies: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("strategy_name"))
        for row in strategies
        if row.get("status") in ACTIVE_STATUSES and row.get("strategy_name")
    }


def display_names_by_strategy(strategies: list[dict[str, Any]]) -> dict[str, str]:
    result = {}
    for row in strategies:
        strategy_name = str(row.get("strategy_name") or "")
        display_name = str(row.get("display_name") or "")
        if strategy_name and display_name:
            result[strategy_name] = display_name
    return result


def with_display_names(rows: list[dict[str, Any]], strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    display_by_name = display_names_by_strategy(strategies)
    enriched = []
    for row in rows:
        item = dict(row)
        name = str(item.get("strategy_name") or "")
        item["display_name"] = display_by_name.get(name, name)
        enriched.append(item)
    return enriched


def daily_pnl_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        trade_date = str(row.get("trade_date") or "")
        if trade_date:
            grouped[trade_date].append(row)
    result = []
    running_total = 0.0
    for trade_date in sorted(grouped):
        day_rows = grouped[trade_date]
        total_pnl = sum(float(row.get("pnl_pct") or 0.0) for row in day_rows)
        running_total += total_pnl
        result.append(
            {
                "trade_date": trade_date,
                "trades": len(day_rows),
                "total_pnl": total_pnl,
                "running_total": running_total,
            }
        )
    return result


def fmt_pct(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def summary_cards(title: str, summary: dict[str, Any]) -> str:
    result_class = "good" if summary["total_pnl"] > 0 else "bad" if summary["total_pnl"] < 0 else ""
    return f"""
    <section class="card">
      <h2>{esc(title)}</h2>
      <div class="metric-grid">
        <div><b>{summary['trades']}</b><span>거래</span></div>
        <div><b>{summary['wins']} / {summary['losses']}</b><span>승 / 패</span></div>
        <div><b>{summary['win_rate']:.1f}%</b><span>승률</span></div>
        <div><b class="{result_class}">{fmt_pct(summary['avg_pnl'])}</b><span>평균</span></div>
        <div><b class="{result_class}">{fmt_pct(summary['total_pnl'])}</b><span>합계</span></div>
        <div><b>{fmt_pct(summary['best'])} / {fmt_pct(summary['worst'])}</b><span>최고 / 최악</span></div>
      </div>
    </section>
    """


def strategy_table(rows: list[dict[str, Any]], strategies: list[dict[str, Any]]) -> str:
    version_by_name: dict[str, list[str]] = defaultdict(list)
    status_by_name: dict[str, list[str]] = defaultdict(list)
    display_by_name = display_names_by_strategy(strategies)
    for strategy in strategies:
        name = str(strategy.get("strategy_name") or "")
        if not name:
            continue
        version_by_name[name].append(str(strategy.get("version") or ""))
        status_by_name[name].append(str(strategy.get("status") or ""))

    body = []
    for row in rows:
        cls = "good" if row["total_pnl"] > 0 else "bad" if row["total_pnl"] < 0 else ""
        name = row["strategy_name"]
        display_name = display_by_name.get(name, name)
        body.append(
            "<tr>"
            f"<td><b>{esc(display_name)}</b><small><code>{esc(name)}</code></small><small>{esc(', '.join(version_by_name.get(name, [])))}</small></td>"
            f"<td>{esc(', '.join(status_by_name.get(name, [])))}</td>"
            f"<td>{row['trades']}</td>"
            f"<td>{row['wins']} / {row['losses']}</td>"
            f"<td>{row['win_rate']:.1f}%</td>"
            f"<td class='{cls}'>{fmt_pct(row['avg_pnl'])}</td>"
            f"<td class='{cls}'>{fmt_pct(row['total_pnl'])}</td>"
            f"<td>{fmt_pct(row['best'])} / {fmt_pct(row['worst'])}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>전략</th><th>상태</th><th>거래</th><th>승/패</th>"
        "<th>승률</th><th>평균</th><th>합계</th><th>최고/최악</th></tr></thead><tbody>"
        + "\n".join(body)
        + "</tbody></table>"
    )


def strategy_totals(rows: list[dict[str, Any]], strategies: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='sub'>전략별 거래 데이터가 없습니다.</p>"
    return strategy_table(group_by_strategy(rows), strategies)


def trades_table(rows: list[dict[str, Any]], limit: int = 30) -> str:
    body = []
    for row in sorted(rows, key=lambda x: str(x.get("closed_at") or ""), reverse=True)[:limit]:
        pnl = float(row.get("pnl_pct") or 0.0)
        cls = "good" if pnl > 0 else "bad" if pnl < 0 else ""
        body.append(
            "<tr>"
            f"<td>{esc(row.get('trade_date'))}</td>"
            f"<td><b>{esc(row.get('symbol'))}</b></td>"
            f"<td><code>{esc(row.get('algorithm'))}</code></td>"
            f"<td>{esc(row.get('opened_at'))}</td>"
            f"<td>{esc(row.get('closed_at'))}</td>"
            f"<td>{float(row.get('entry_price') or 0.0):.4f}</td>"
            f"<td>{float(row.get('exit_price') or 0.0):.4f}</td>"
            f"<td class='{cls}'>{fmt_pct(pnl)}</td>"
            f"<td>{esc(row.get('reason'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>일자</th><th>종목</th><th>전략</th><th>매수</th><th>매도</th>"
        "<th>매수가</th><th>매도가</th><th>손익</th><th>사유</th></tr></thead><tbody>"
        + "\n".join(body)
        + "</tbody></table>"
    )


def compact_trades_table(rows: list[dict[str, Any]], limit: int = 20) -> str:
    body = []
    for row in sorted(rows, key=lambda x: str(x.get("opened_at") or ""), reverse=True)[:limit]:
        pnl = float(row.get("pnl_pct") or 0.0)
        cls = "good" if pnl > 0 else "bad" if pnl < 0 else ""
        body.append(
            "<tr>"
            f"<td>{esc(row.get('trade_date'))}</td>"
            f"<td><b>{esc(row.get('symbol'))}</b></td>"
            f"<td>{esc(row.get('opened_at'))}</td>"
            f"<td class='{cls}'>{fmt_pct(pnl)}</td>"
            f"<td>{esc(row.get('reason'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>일자</th><th>종목</th><th>진입</th><th>손익</th><th>사유</th></tr></thead><tbody>"
        + "\n".join(body)
        + "</tbody></table>"
    )


def performance_charts(recent: list[dict[str, Any]], strategies: list[dict[str, Any]]) -> str:
    strategy_rows = with_display_names(group_by_strategy(recent), strategies)
    daily_rows = daily_pnl_series(recent)
    payload = {
        "strategy_labels": [row["display_name"] for row in strategy_rows],
        "strategy_total_pnl": [round(float(row["total_pnl"]), 4) for row in strategy_rows],
        "strategy_win_rate": [round(float(row["win_rate"]), 4) for row in strategy_rows],
        "daily_labels": [row["trade_date"] for row in daily_rows],
        "daily_pnl": [round(float(row["total_pnl"]), 4) for row in daily_rows],
        "daily_running_pnl": [round(float(row["running_total"]), 4) for row in daily_rows],
    }
    data = json.dumps(payload, ensure_ascii=False)
    return f"""
    <section class="chart-grid">
      <div class="card"><h2>전략별 누적 손익</h2><canvas id="strategyPnlChart" height="120"></canvas></div>
      <div class="card"><h2>전략별 승률</h2><canvas id="strategyWinRateChart" height="120"></canvas></div>
      <div class="card wide"><h2>최근 일별 손익 흐름</h2><canvas id="dailyPnlChart" height="90"></canvas></div>
    </section>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <script>
      const chartData = {data};
      const textColor = "#e5e7eb";
      const gridColor = "rgba(148, 163, 184, 0.18)";
      const good = "#38d996";
      const bad = "#ff6b6b";
      const accent = "#7dd3fc";
      function pnlColors(values) {{
        return values.map((value) => value >= 0 ? good : bad);
      }}
      function baseOptions(percentSuffix = true) {{
        return {{
          responsive: true,
          plugins: {{
            legend: {{ labels: {{ color: textColor }} }},
            tooltip: {{ callbacks: {{ label: (ctx) => `${{ctx.dataset.label}}: ${{ctx.parsed.y.toFixed(2)}}${{percentSuffix ? "%" : ""}}` }} }}
          }},
          scales: {{
            x: {{ ticks: {{ color: textColor }}, grid: {{ color: gridColor }} }},
            y: {{ ticks: {{ color: textColor }}, grid: {{ color: gridColor }} }}
          }}
        }};
      }}
      new Chart(document.getElementById("strategyPnlChart"), {{
        type: "bar",
        data: {{
          labels: chartData.strategy_labels,
          datasets: [{{ label: "합계 손익", data: chartData.strategy_total_pnl, backgroundColor: pnlColors(chartData.strategy_total_pnl) }}]
        }},
        options: baseOptions()
      }});
      new Chart(document.getElementById("strategyWinRateChart"), {{
        type: "bar",
        data: {{
          labels: chartData.strategy_labels,
          datasets: [{{ label: "승률", data: chartData.strategy_win_rate, backgroundColor: accent }}]
        }},
        options: baseOptions()
      }});
      new Chart(document.getElementById("dailyPnlChart"), {{
        type: "line",
        data: {{
          labels: chartData.daily_labels,
          datasets: [
            {{ label: "일별 손익", data: chartData.daily_pnl, borderColor: accent, backgroundColor: "rgba(125, 211, 252, .18)", tension: .25 }},
            {{ label: "누적 손익", data: chartData.daily_running_pnl, borderColor: good, backgroundColor: "rgba(56, 217, 150, .12)", tension: .25 }}
          ]
        }},
        options: baseOptions()
      }});
    </script>
    """


def admin_table(strategies: list[dict[str, Any]]) -> str:
    rows = []
    for strategy in strategies:
        rows.append(
            "<tr>"
            f"<td><code>{esc(strategy.get('version'))}</code></td>"
            f"<td><input name='display_name' value='{esc(strategy.get('display_name'))}' form='form-{esc(strategy.get('version'))}'></td>"
            f"<td><code>{esc(strategy.get('strategy_name'))}</code></td>"
            f"<td>{esc(strategy.get('type'))}</td>"
            "<td>"
            f"<form id='form-{esc(strategy.get('version'))}' method='post' action='/admin/strategies/update' class='inline-form'>"
            f"<input type='hidden' name='version' value='{esc(strategy.get('version'))}'>"
            f"<input name='status' value='{esc(strategy.get('status'))}'>"
            "</td><td>"
            f"<textarea name='decision'>{esc(strategy.get('decision'))}</textarea>"
            "</td><td>"
            "<button type='submit'>저장</button></form>"
            "</td></tr>"
        )
    return (
        "<table><thead><tr><th>버전</th><th>표시명</th><th>전략명</th><th>타입</th><th>상태</th>"
        "<th>판단/메모</th><th>관리</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )


def layout(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{ --bg:#0f172a; --panel:#111827; --muted:#94a3b8; --text:#e5e7eb; --line:#253044; --good:#38d996; --bad:#ff6b6b; --accent:#7dd3fc; }}
    body {{ margin:0; background:linear-gradient(140deg,#0f172a,#111827 45%,#172554); color:var(--text); font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif; }}
    main {{ width:min(1180px, calc(100% - 28px)); margin:24px auto 56px; }}
    nav {{ display:flex; gap:12px; margin:0 0 18px; }}
    nav a {{ color:var(--accent); text-decoration:none; font-weight:700; }}
    h1 {{ font-size:28px; margin:0 0 8px; }}
    h2 {{ margin:0 0 14px; font-size:18px; }}
    .sub {{ color:var(--muted); margin:0 0 18px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }}
    .chart-grid {{ display:grid; grid-template-columns:repeat(2,minmax(280px,1fr)); gap:14px; margin:18px 0 26px; }}
    .chart-grid .wide {{ grid-column:1 / -1; }}
    .card {{ background:rgba(17,24,39,.88); border:1px solid var(--line); border-radius:18px; padding:18px; box-shadow:0 12px 40px rgba(0,0,0,.25); }}
    .metric-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .metric-grid div {{ background:#0b1220; border:1px solid #1f2937; border-radius:12px; padding:10px; }}
    .metric-grid b {{ display:block; font-size:20px; }}
    .metric-grid span, small {{ color:var(--muted); font-size:12px; display:block; margin-top:4px; }}
    table {{ width:100%; border-collapse:collapse; background:rgba(17,24,39,.88); border:1px solid var(--line); border-radius:16px; overflow:hidden; margin:14px 0 26px; }}
    th, td {{ border-bottom:1px solid var(--line); padding:10px; text-align:left; vertical-align:top; font-size:13px; }}
    th {{ color:#bfdbfe; background:#0b1220; }}
    code {{ color:#bae6fd; white-space:normal; }}
    input, textarea {{ width:100%; box-sizing:border-box; border:1px solid #334155; border-radius:8px; background:#0b1220; color:var(--text); padding:8px; }}
    textarea {{ min-height:58px; }}
    button {{ border:0; border-radius:10px; padding:9px 14px; background:#38bdf8; color:#082f49; font-weight:800; cursor:pointer; }}
    .good {{ color:var(--good); }}
    .bad {{ color:var(--bad); }}
    .section-title {{ margin-top:26px; }}
    @media (max-width:760px) {{ .chart-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body><main>
  <nav><a href="/">Dashboard</a><a href="/admin/strategies">Strategy Admin</a><a href="/api/summary">API Summary</a></nav>
  {body}
</main></body></html>""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "MarketAdmin/0.1"

    def send_html(self, title: str, body: str, status: int = 200) -> None:
        payload = layout(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        days = int(qs.get("days", ["10"])[0])
        ledger = read_jsonl(LEDGER_PATH)
        strategies = read_strategies()
        recent = recent_rows(ledger, days)
        active_names = active_strategy_names(strategies)
        active_recent = [row for row in recent if row.get("algorithm") in active_names]
        d1_policy_rows = d1_current_policy_rows(ledger)
        d1_policy_excluded = d1_excluded_by_policy_rows(ledger)

        if parsed.path == "/api/summary":
            self.send_json(
                {
                    "days": days,
                    "all_recent": summarize(recent),
                    "active_recent": summarize(active_recent),
                    "by_strategy_recent": with_display_names(group_by_strategy(recent), strategies),
                    "by_strategy_all": with_display_names(group_by_strategy(ledger), strategies),
                    "d1_current_policy": summarize(d1_policy_rows),
                    "d1_current_policy_excluded": summarize(d1_policy_excluded),
                    "active_strategy_names": sorted(active_names),
                }
            )
            return

        if parsed.path == "/admin/strategies":
            self.send_html(
                "Strategy Admin",
                f"<h1>Strategy Admin</h1><p class='sub'>전략 상태와 판단 메모를 관리합니다. 저장 대상: {esc(STRATEGY_PATH)}</p>{admin_table(strategies)}",
            )
            return

        if parsed.path != "/":
            self.send_html("Not Found", "<h1>404</h1>", 404)
            return

        body = (
            f"<h1>SQream Market Lab</h1><p class='sub'>최근 {days}거래일 기준. active/candidate 전략과 전체 전략을 분리 집계합니다.</p>"
            "<div class='cards'>"
            + summary_cards("최근 활성/후보 전략", summarize(active_recent))
            + summary_cards("최근 전체 전략", summarize(recent))
            + summary_cards("D1 현재 룰", summarize(d1_policy_rows))
            + "</div>"
            "<h2 class='section-title'>성과 차트</h2>"
            + performance_charts(recent, strategies)
            + "<h2 class='section-title'>D1거래량돌파 현재 룰 상세</h2>"
            + "<p class='sub'>09:30~10:15 ET 진입만 포함합니다. 과거 비정책 구간 거래는 제외합니다.</p>"
            + compact_trades_table(d1_policy_rows)
            + "<h2 class='section-title'>D1 현재 룰 제외 거래</h2>"
            + compact_trades_table(d1_policy_excluded)
            + "<h2 class='section-title'>전략별 최근 집계</h2>"
            + strategy_table(group_by_strategy(recent), strategies)
            + "<h2 class='section-title'>전략별 전체 누적 집계</h2>"
            + strategy_totals(ledger, strategies)
            + "<h2 class='section-title'>최근 거래 상세</h2>"
            + trades_table(recent)
        )
        self.send_html("SQream Market Lab", body)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/admin/strategies/update":
            self.send_html("Not Found", "<h1>404</h1>", 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(body)
        version = (form.get("version") or [""])[0]
        status = (form.get("status") or [""])[0].strip()
        display_name = (form.get("display_name") or [""])[0].strip()
        decision = (form.get("decision") or [""])[0].strip()
        strategies = read_strategies()
        updated = False
        for row in strategies:
            if row.get("version") == version:
                row["display_name"] = display_name
                row["status"] = status
                row["decision"] = decision
                updated = True
                break
        if updated:
            write_strategies(strategies)
        self.send_response(303)
        self.send_header("Location", "/admin/strategies")
        self.end_headers()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18085)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Market admin web listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
