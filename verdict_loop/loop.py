"""The screening loop.

One pass:
  1. For every token on the watchlist, ask Token Verdict for a risk
     verdict and turn it into a WOULD_BUY / SKIP screening decision.
  2. For every newly discovered x402 service, ask RouteVerdict whether
     the endpoint is trustworthy enough to ADOPT / PASS.
  3. Print a run summary: what was spent (live) or would be spent
     (dry-run) against the daily cap.

Modes:
  DRY-RUN (default): no payment can happen. The loop makes only the
  unpaid request, parses the real 402 challenge, and reports the exact
  price it *would* pay plus the standing decision policy. It never
  invents a verdict.
  LIVE: requires BOTH the --live flag and a signer in the environment
  (AGENT_PRIVATE_KEY or AGENT_KEY_FILE). Every payment is authorized
  against the daily spend cap before it is signed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .budget import DailySpendCap
from .decide import (
    DEFAULT_MAX_RISK_SCORE,
    DEFAULT_MIN_TRUST_SCORE,
    decide_service,
    decide_token,
)
from .x402 import (
    ServiceError,
    call_paid_endpoint,
    format_usd,
    load_account_from_env,
)

DEFAULT_TOKEN_VERDICT_URL = "https://token-verdict-production.up.railway.app/v1/verdict"
DEFAULT_ROUTE_VERDICT_URL = "https://route-verdict-production.up.railway.app/v1/check"
USDC_UNITS_PER_DOLLAR = 1_000_000


def _scrub_no_proxy() -> None:
    """Drop bracketed-IPv6 entries from no_proxy.

    Some sandboxes ship no_proxy values like "[::1],localhost" that
    crash httpx's proxy parsing. Scrubbing just the bracketed entries
    (mirroring RouteVerdict's own startup fix) keeps normal hosts
    unaffected.
    """
    for var in ("no_proxy", "NO_PROXY"):
        raw = os.environ.get(var)
        if raw and "[" in raw:
            kept = [p for p in raw.split(",") if "[" not in p]
            os.environ[var] = ",".join(kept)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path: str | Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")
    return config


def run_pass(config: dict, *, live: bool, out=print) -> int:
    policy = config.get("policy") or {}
    max_risk = float(policy.get("max_risk_score", DEFAULT_MAX_RISK_SCORE))
    min_trust = float(policy.get("min_trust_score", DEFAULT_MIN_TRUST_SCORE))
    cap_units = int(round(float(config.get("daily_cap_usd", 0.10)) * USDC_UNITS_PER_DOLLAR))
    token_url = config.get("token_verdict_url", DEFAULT_TOKEN_VERDICT_URL)
    route_url = config.get("route_verdict_url", DEFAULT_ROUTE_VERDICT_URL)
    tokens = config.get("tokens") or []
    services = config.get("services_to_check") or []

    # --- mode + signer ------------------------------------------------------
    account = None
    if live:
        account = load_account_from_env()
        if account is None:
            out("ERROR: --live given but no signer in the environment "
                "(set AGENT_PRIVATE_KEY or AGENT_KEY_FILE). Refusing to run.")
            return 2
    budget = None
    if live:
        state = config.get("budget_state", "verdict-loop-budget.json")
        budget = DailySpendCap(cap_units, state_path=state)

    mode_label = "LIVE" if live else "DRY-RUN"
    out(f"=== verdict-loop pass @ {_ts()} — mode: {mode_label} ===")
    if live:
        out(f"payer: {account.address} | daily cap: {format_usd(cap_units)} "
            f"| already spent today: {format_usd(budget.spent_units)}")
    else:
        out("no payments will be made; every line below is a parsed live "
            "402 challenge plus the standing policy")
        out(f"daily cap (for live mode): {format_usd(cap_units)}")

    errors = 0
    would_spend = 0
    spent = 0
    planned: list[int] = []  # prices in call order, for the dry-run cap projection

    _scrub_no_proxy()
    with httpx.Client(timeout=30.0) as http:
        # --- 1. token screening ---------------------------------------------
        for entry in tokens:
            address = entry["address"]
            chain = entry.get("chain", "base")
            label = entry.get("label", address)
            try:
                outcome = call_paid_endpoint(
                    http, token_url, {"address": address, "chain": chain},
                    account=account, budget=budget,
                )
            except ServiceError as exc:
                errors += 1
                out(f"[token] {label} ({address}, {chain}): ERROR {exc}")
                continue
            planned.append(outcome.price_units)
            if outcome.mode == "dry_run":
                would_spend += outcome.price_units
                req = outcome.requirement or {}
                out(f"[token] {label} ({address}, {chain}): DRY-RUN would pay "
                    f"{format_usd(outcome.price_units)} to {req.get('payTo')} on "
                    f"{req.get('network')} for a Token Verdict screening")
                out(f"        policy on the verdict: WOULD_BUY only if SOLID and "
                    f"risk score <= {max_risk:g}; otherwise SKIP")
            elif outcome.mode == "blocked":
                out(f"[token] {label}: BLOCKED by spend cap — {outcome.note}")
            else:
                spent += outcome.price_units
                verdict = outcome.response or {}
                decision = decide_token(verdict, max_risk_score=max_risk)
                symbol = (verdict.get("token") or {}).get("symbol", "?")
                take = str(verdict.get("take", ""))[:140]
                out(f"[token] {label} ({symbol}): verdict {decision.verdict} "
                    f"risk {decision.score:g} -> {decision.action} ({decision.reason})")
                if take:
                    out(f"        take: {take}")
                tx = (outcome.receipt or {}).get("transaction")
                if tx:
                    out(f"        settlement tx: {tx}")

        # --- 2. new-service checks -------------------------------------------
        for resource_url in services:
            try:
                outcome = call_paid_endpoint(
                    http, route_url, {"resource_url": resource_url},
                    account=account, budget=budget,
                )
            except ServiceError as exc:
                errors += 1
                out(f"[service] {resource_url}: ERROR {exc}")
                continue
            planned.append(outcome.price_units)
            if outcome.mode == "dry_run":
                would_spend += outcome.price_units
                req = outcome.requirement or {}
                out(f"[service] {resource_url}: DRY-RUN would pay "
                    f"{format_usd(outcome.price_units)} to {req.get('payTo')} on "
                    f"{req.get('network')} for a RouteVerdict trust check")
                out(f"        policy on the check: ADOPT only if TRUSTED and "
                    f"trust score >= {min_trust:g}; otherwise PASS")
            elif outcome.mode == "blocked":
                out(f"[service] {resource_url}: BLOCKED by spend cap — {outcome.note}")
            else:
                spent += outcome.price_units
                check = outcome.response or {}
                decision = decide_service(check, min_trust_score=min_trust)
                out(f"[service] {resource_url}: verdict {decision.verdict} "
                    f"trust {decision.score:g} -> {decision.action} ({decision.reason})")
                tx = (outcome.receipt or {}).get("transaction")
                if tx:
                    out(f"        settlement tx: {tx}")

    # --- 3. summary -----------------------------------------------------------
    out("--- summary ---")
    out(f"calls planned: {len(planned)} | errors: {errors}")
    if live:
        out(f"spent this pass: {format_usd(spent)} | spent today: "
            f"{format_usd(budget.spent_units)} of {format_usd(cap_units)} cap")
    else:
        out(f"would spend: {format_usd(would_spend)} against a "
            f"{format_usd(cap_units)} daily cap")
        running = 0
        fits = 0
        for price in planned:
            if running + price <= cap_units:
                running += price
                fits += 1
            else:
                break
        if fits < len(planned):
            out(f"cap projection: only the first {fits} of {len(planned)} calls fit "
                f"under the cap ({format_usd(running)}); the rest would be BLOCKED "
                f"in live mode")
        else:
            out(f"cap projection: all {len(planned)} calls fit under the cap")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verdict-loop",
        description="Reference screening agent: Token Verdict + RouteVerdict "
                    "inside an agent loop (dry-run by default).",
    )
    parser.add_argument("--config", default="config.json",
                        help="watchlist config JSON (default: config.json)")
    parser.add_argument("--live", action="store_true",
                        help="actually pay (also requires AGENT_PRIVATE_KEY or "
                             "AGENT_KEY_FILE in the environment)")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot load config {args.config}: {exc}", file=sys.stderr)
        return 2
    return run_pass(config, live=args.live)


if __name__ == "__main__":
    raise SystemExit(main())
