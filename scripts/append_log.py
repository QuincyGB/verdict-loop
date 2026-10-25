#!/usr/bin/env python3
"""Append one dated entry to docs/live-log.md from a captured run.

Usage:
    python3 scripts/append_log.py --output RUN.txt --exit-code N \
        [--log docs/live-log.md] [--budget-state verdict-loop-budget.json]

The parser reads the loop's own stdout format (verdict_loop/loop.py):
token/service verdict lines, settlement tx lines, the Settled
pre-flight lines, the balance-guard lines, and the closing summary.
Each entry ends with a machine-readable marker
(<!-- entry spent_usd=… cumulative_usd=… -->) so the cumulative total
survives across runs without trusting prose. If the summary line is
missing (a crash mid-pass), the day's settled total is taken from the
budget ledger instead, when its date matches the run date.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RE_PASS_TS = re.compile(r"=== verdict-loop pass @ (\S+) — mode: (\S+) ===")
RE_TOKEN = re.compile(
    r"\[token\] (.*): verdict (\S+) risk (\S+) -> (\S+) \((.*)\)")
RE_TOKEN_OTHER = re.compile(r"\[token\] (.*?)(?:: (BLOCKED|DRY-RUN|ERROR) .*)?$")
RE_SERVICE = re.compile(
    r"\[service\] (\S+): verdict (\S+) trust (\S+) -> (\S+) \((.*)\)")
RE_SERVICE_VETO = re.compile(r"\[service\] (\S+): -> PASS \(Settled pre-flight veto")
RE_SERVICE_OTHER = re.compile(r"\[service\] (\S+): (BLOCKED|ERROR) ?(.*)")
RE_SETTLED = re.compile(r"\[settled\] (\S+): (.*)")
RE_TX = re.compile(r"settlement tx: (\S+)")
RE_TAKE = re.compile(r"take: (.*)")
RE_BALANCE_OK = re.compile(
    r"balance guard: payer holds (\$\S+) USDC on Base; planned spend (\$\S+)")
RE_BALANCE_WARN = re.compile(r"balance guard: WARNING")
RE_INSUFFICIENT = re.compile(
    r"INSUFFICIENT FUNDS: payer \S+ holds (\$\S+) USDC on Base, "
    r"but this pass plans to spend (\$\S+)")
RE_SPENT = re.compile(
    r"spent this pass: \$([\d.]+) \| spent today: \$([\d.]+) of \$([\d.]+) cap")
RE_CALLS = re.compile(r"calls planned: (\d+) \| errors: (\d+)")
RE_MARKER = re.compile(r"<!-- entry spent_usd=([\d.]+) cumulative_usd=([\d.]+) -->")


def _attach_tx(entries: list[dict], tx: str) -> None:
    for entry in reversed(entries):
        if entry.get("kind") in ("token", "service") and "tx" not in entry:
            entry["tx"] = tx
            return


def parse_run(text: str) -> dict:
    run: dict = {"entries": [], "raw": text}
    current_take_target: dict | None = None
    for line in text.splitlines():
        line = line.rstrip()
        m = RE_PASS_TS.search(line)
        if m:
            run["started_at"] = m.group(1)
            run["mode"] = m.group(2)
            continue
        m = RE_TOKEN.search(line)
        if m:
            entry = {"kind": "token", "label": m.group(1),
                     "verdict": m.group(2), "score": m.group(3),
                     "action": m.group(4), "reason": m.group(5)}
            run["entries"].append(entry)
            current_take_target = entry
            continue
        m = RE_SERVICE.search(line)
        if m:
            entry = {"kind": "service", "label": m.group(1),
                     "verdict": m.group(2), "score": m.group(3),
                     "action": m.group(4), "reason": m.group(5)}
            run["entries"].append(entry)
            current_take_target = None
            continue
        m = RE_SERVICE_VETO.search(line)
        if m:
            run["entries"].append(
                {"kind": "service", "label": m.group(1),
                 "action": "PASS", "reason": "Settled pre-flight veto — "
                 "paid check skipped, nothing paid"})
            current_take_target = None
            continue
        m = RE_SETTLED.search(line)
        if m:
            run["entries"].append(
                {"kind": "settled", "label": m.group(1), "note": m.group(2)})
            continue
        m = RE_TX.search(line)
        if m:
            _attach_tx(run["entries"], m.group(1))
            continue
        m = RE_TAKE.search(line)
        if m and current_take_target is not None:
            current_take_target["take"] = m.group(1)
            continue
        m = RE_SERVICE_OTHER.search(line)
        if m and not any(e.get("label") == m.group(1) and e["kind"] == "service"
                         for e in run["entries"]):
            run["entries"].append(
                {"kind": "service", "label": m.group(1),
                 "action": m.group(2), "reason": m.group(3)})
            continue
        m = RE_BALANCE_OK.search(line)
        if m:
            run["balance"] = m.group(1)
            run["planned"] = m.group(2)
            continue
        if RE_BALANCE_WARN.search(line):
            run["balance_warning"] = True
            continue
        m = RE_INSUFFICIENT.search(line)
        if m:
            run["insufficient"] = {"balance": m.group(1), "planned": m.group(2)}
            continue
        m = RE_SPENT.search(line)
        if m:
            run["spent_pass"] = float(m.group(1))
            run["spent_today"] = float(m.group(2))
            run["cap"] = float(m.group(3))
            continue
        m = RE_CALLS.search(line)
        if m:
            run["calls_planned"] = int(m.group(1))
            run["errors"] = int(m.group(2))
            continue
    return run


def ledger_spent_units(budget_state: Path, date: str) -> int | None:
    try:
        data = json.loads(budget_state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("date") == date:
        return int(data.get("spent_units", 0))
    return None


def render_entry(run: dict, *, date: str, exit_code: int,
                 prior_cumulative: float) -> tuple[str, float]:
    spent = run.get("spent_pass")
    if spent is None:
        spent = 0.0
    cumulative = prior_cumulative + spent

    lines: list[str] = []
    status = "live run" if exit_code == 0 else f"live run (exit {exit_code})"
    if run.get("insufficient"):
        status = "skipped — insufficient funds (nothing signed, nothing paid)"
    lines.append(f"## {date} — {status}")
    lines.append("")
    if run.get("insufficient"):
        ins = run["insufficient"]
        lines.append(
            f"- **Balance guard stopped this run:** payer held "
            f"{ins['balance']} USDC against a planned spend of "
            f"{ins['planned']}. No payment was attempted.")
    elif run.get("balance"):
        lines.append(
            f"- **Balance guard:** payer held {run['balance']} USDC; "
            f"planned spend {run['planned']}.")
    elif run.get("balance_warning"):
        lines.append(
            "- **Balance guard:** payer balance unreadable (public RPCs "
            "down); the run proceeded on the spend cap alone.")

    tokens = [e for e in run["entries"] if e["kind"] == "token"]
    services = [e for e in run["entries"] if e["kind"] == "service"]
    settled = [e for e in run["entries"] if e["kind"] == "settled"]

    if tokens:
        lines.append("- **Tokens screened:**")
        for e in tokens:
            head = f"  - {e['label']}"
            if e.get("verdict"):
                head += (f": verdict **{e['verdict']}**, risk {e['score']} "
                         f"→ **{e['action']}** ({e['reason']})")
            else:
                head += f": {e.get('action', 'no result')}"
            lines.append(head)
            if e.get("take"):
                lines.append(f"    - take: {e['take']}")
            if e.get("tx"):
                lines.append(
                    f"    - settlement tx: [`{e['tx']}`]"
                    f"(https://basescan.org/tx/{e['tx']})")
    if settled:
        lines.append("- **Settled pre-flight:**")
        for e in settled:
            lines.append(f"  - {e['label']}: {e['note']}")
    if services:
        lines.append("- **Services vetted:**")
        for e in services:
            head = f"  - {e['label']}"
            if e.get("verdict"):
                head += (f": verdict **{e['verdict']}**, trust {e['score']} "
                         f"→ **{e['action']}** ({e['reason']})")
            else:
                head += (f": **{e.get('action', 'no result')}** "
                         f"({e.get('reason', '')})")
            lines.append(head)
            if e.get("tx"):
                lines.append(
                    f"    - settlement tx: [`{e['tx']}`]"
                    f"(https://basescan.org/tx/{e['tx']})")
    if run.get("calls_planned") is not None:
        lines.append(
            f"- **Calls:** {run['calls_planned']} planned, "
            f"{run.get('errors', 0)} errors.")
    if run.get("spent_pass") is not None:
        lines.append(
            f"- **Spent:** ${spent:.2f} this run "
            f"(${run['spent_today']:.2f} today of ${run['cap']:.2f} cap) · "
            f"**Cumulative logged spend: ${cumulative:.6f}**")
    else:
        lines.append(
            f"- **Spent:** no summary line in the run output (see raw log "
            f"below) · **Cumulative logged spend: ${cumulative:.6f}**")
    lines.append("")
    lines.append("<details><summary>Full run output</summary>")
    lines.append("")
    lines.append("```text")
    lines.append(run["raw"].rstrip())
    lines.append("```")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append(
        f"<!-- entry spent_usd={spent:.6f} cumulative_usd={cumulative:.6f} -->")
    lines.append("")
    return "\n".join(lines), cumulative


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True,
                        help="file with the captured loop stdout")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--log", default="docs/live-log.md")
    parser.add_argument("--budget-state", default="verdict-loop-budget.json")
    args = parser.parse_args(argv)

    text = Path(args.output).read_text(encoding="utf-8")
    run = parse_run(text)

    started = run.get("started_at")
    if started:
        date = started[:10]
    else:
        date = datetime.now(timezone.utc).date().isoformat()

    # Fallback spend figure: the budget ledger, when the run crashed
    # before printing its summary but its date matches the ledger's.
    if run.get("spent_pass") is None and not run.get("insufficient"):
        units = ledger_spent_units(Path(args.budget_state), date)
        if units is not None:
            run["spent_pass"] = units / 1_000_000

    log_path = Path(args.log)
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    markers = RE_MARKER.findall(existing)
    prior = float(markers[-1][1]) if markers else 0.0

    entry, _ = render_entry(run, date=date, exit_code=args.exit_code,
                            prior_cumulative=prior)
    with log_path.open("a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write(entry)
    print(f"append_log: appended {date} entry to {log_path} "
          f"(exit {args.exit_code})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
