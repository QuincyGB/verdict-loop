"""scripts/append_log.py — the public log must never lose a day.

Regression home for the 2026-10-25 08:00 failure: the run crashed
before printing its summary, the budget-ledger fallback supplied a
spend figure without spent_today/cap, and render_entry died with
KeyError 'spent_today' — so a day on which money actually moved got
no log entry at all. These tests pin: the renderer tolerates partial
spend fields, the ledger fallback derives the PASS spend from the
day total (never conflating the two), and a cap stop renders as a
completed policy stop.
"""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "append_log.py"
spec = importlib.util.spec_from_file_location("append_log", SCRIPT)
append_log = importlib.util.module_from_spec(spec)
spec.loader.exec_module(append_log)

DATE = "2026-10-25"
TOKEN_LINE = (
    "[token] Wrapped Ether (Base) (WETH): verdict SOLID risk 16.4 "
    "-> WOULD_BUY (SOLID with risk score 16.4 <= max 40)"
)
TX_LINE = "        settlement tx: 0xe4ff82a8b1ab1e49b54fab612c658273f91d657b610484107513a667991d1a82"


def test_parse_and_render_a_cap_stop_run():
    text = "\n".join([
        f"=== verdict-loop pass @ {DATE}T11:57:18Z — mode: LIVE ===",
        TOKEN_LINE,
        TX_LINE,
        "[service] https://token-verdict-production.up.railway.app/v1/verdict: "
        "BLOCKED by spend cap — optional service check skipped before signing",
        "--- summary ---",
        "calls planned: 3 | errors: 0",
        "cap stop: optional service check skipped before signing: worst "
        "case $0.05 exceeds the $0.015 left of today's $0.10 cap",
        "spent this pass: $0.045 | spent today: $0.085 of $0.10 cap",
    ])
    run = append_log.parse_run(text)
    assert run["cap_stop"].startswith("optional service check skipped")
    assert run["spent_pass"] == 0.045
    entry, cumulative = append_log.render_entry(
        run, date=DATE, exit_code=0, prior_cumulative=0.04)
    assert "completed with cap stop (policy stop, not an error)" in entry
    assert "**Cap stop:**" in entry
    assert "WOULD_BUY" in entry
    assert cumulative == pytest.approx(0.085)
    assert "spent_usd=0.045000 cumulative_usd=0.085000" in entry


def test_render_tolerates_spend_fields_the_guard_path_leaves_missing():
    # spent_pass with no spent_today / cap: the exact shape that
    # KeyError'd on 2026-10-25.
    run = {"entries": [], "raw": "crashed before the summary",
           "spent_pass": 0.045}
    entry, cumulative = append_log.render_entry(
        run, date=DATE, exit_code=1, prior_cumulative=0.04)
    assert "spent_usd=0.045000 cumulative_usd=0.085000" in entry
    assert cumulative == pytest.approx(0.085)


def test_main_ledger_fallback_derives_pass_spend(tmp_path):
    # A crashed run: header + settled token lines, NO summary. The
    # ledger says $0.085 settled today; the log already holds an
    # earlier same-date entry for $0.04. The appended entry must
    # record THIS pass as $0.045 — not the $0.085 day total.
    log = tmp_path / "live-log.md"
    log.write_text(
        "# log\n\n"
        f"## {DATE} — live run\n\n"
        "<!-- entry spent_usd=0.040000 cumulative_usd=0.040000 -->\n",
        encoding="utf-8")
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps(
        {"date": DATE, "cap_units": 100000, "spent_units": 85000,
         "calls": []}), encoding="utf-8")
    out = tmp_path / "run.txt"
    out.write_text("\n".join([
        f"=== verdict-loop pass @ {DATE}T11:57:18Z — mode: LIVE ===",
        TOKEN_LINE,
        TX_LINE,
        "[service] https://token-verdict-production.up.railway.app/v1/verdict: "
        "BLOCKED by spend cap — paying $0.05 would bring today to $0.135",
        "cap stop: paying $0.05 would bring today to $0.135, over the "
        "$0.10 cap (already spent $0.085)",
    ]), encoding="utf-8")

    code = append_log.main([
        "--output", str(out), "--exit-code", "1",
        "--log", str(log), "--budget-state", str(budget)])
    assert code == 0
    appended = log.read_text(encoding="utf-8")
    assert "spent_usd=0.045000 cumulative_usd=0.085000" in appended
    assert "completed with cap stop (policy stop, not an error)" in appended
    assert "0xe4ff82a8b1ab1e49b54fab612c658273f91d657b610484107513a667991d1a82" \
        in appended


def test_recovered_entries_are_marked():
    run = append_log.parse_run(
        "RECOVERED ENTRY — backfilled from the cron run record.\n"
        f"=== verdict-loop pass @ {DATE}T11:57:18Z — mode: LIVE ===\n")
    assert run["recovered"]
    entry, _ = append_log.render_entry(
        run, date=DATE, exit_code=1, prior_cumulative=0.0)
    assert "recovered/backfilled entry" in entry
    assert "**Recovered entry:**" in entry
