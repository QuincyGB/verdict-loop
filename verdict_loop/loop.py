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
  against the daily spend cap before it is signed. A balance guard
  runs first: the pass is priced with unpaid probes and the payer's
  USDC balance is read from the chain — a known balance below the
  planned spend stops the run cleanly (exit 3, INSUFFICIENT FUNDS)
  before anything is signed; an unreadable balance only warns.

Settled pre-flight: before each service check the loop asks Settled
(settled.tools) — free, read-only — what its scout's test purchases
found about that endpoint. It is advisory plus one narrow veto: a
hard negative on Settled's record means the service is not adopted
whatever RouteVerdict says (in live mode the paid check is skipped
entirely). On by default; --no-settled, SETTLED_CHECK=0, or
"settled_check": false in the config turns it off. A Settled outage
never blocks the loop.

Payment path: every payment the loop makes runs through x402-guard
(the fleet's buyer-side middleware, dogfooded here). The guard's
pipeline — Settled pre-flight (the stage above, same fixed narrow-
veto semantics), a StallRow Recheck drift check on the target
($0.005, cached 24h), a RouteVerdict gate for large first payments,
and spend caps — runs before anything is signed. The loop's
DailySpendCap is handed to the guard as its budget, so every settled
call (the guard's own check calls included) is authorized and
recorded against the one $0.10/day cap. Guard state (drift cache,
audit log) lives in local files named by the config's "guard"
section; both are gitignored.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from x402_guard import GuardBlocked, GuardConfig, GuardedClient
from x402_guard.config import DEFAULT_RECHECK_URL

from .budget import DailySpendCap
from .decide import (
    DEFAULT_MAX_RISK_SCORE,
    DEFAULT_MIN_TRUST_SCORE,
    decide_service,
    decide_token,
)
from .wallet import usdc_balance_units
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


def _settled_enabled(config: dict, override: bool | None) -> bool:
    """Resolve the pre-flight toggle: CLI flag > SETTLED_CHECK env >
    config "settled_check" > default ON."""
    if override is not None:
        return override
    env = (os.environ.get("SETTLED_CHECK") or "").strip().lower()
    if env:
        return env not in ("0", "false", "no", "off")
    if "settled_check" in config:
        return bool(config["settled_check"])
    return True


def run_pass(config: dict, *, live: bool, settled: bool | None = None, out=print) -> int:
    policy = config.get("policy") or {}
    max_risk = float(policy.get("max_risk_score", DEFAULT_MAX_RISK_SCORE))
    min_trust = float(policy.get("min_trust_score", DEFAULT_MIN_TRUST_SCORE))
    cap_units = int(round(float(config.get("daily_cap_usd", 0.10)) * USDC_UNITS_PER_DOLLAR))
    token_url = config.get("token_verdict_url", DEFAULT_TOKEN_VERDICT_URL)
    route_url = config.get("route_verdict_url", DEFAULT_ROUTE_VERDICT_URL)
    tokens = config.get("tokens") or []
    services = config.get("services_to_check") or []
    settled_on = _settled_enabled(config, settled)

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

    if live:
        # --- balance guard --------------------------------------------------
        # Probe every planned call unpaid to price the pass, then read
        # the payer's USDC balance from the chain. A KNOWN balance below
        # the planned spend stops the run cleanly (exit 3) before
        # anything is signed — never mid-screen with a half-paid pass.
        # An unreadable balance (every public RPC down) only warns: the
        # spend cap still bounds the pass, and an RPC outage must not
        # brick the agent.
        _scrub_no_proxy()
        planned_units = 0
        probe_failed = False
        with httpx.Client(timeout=30.0) as probe:
            for entry in tokens:
                try:
                    outcome = call_paid_endpoint(
                        probe, token_url,
                        {"address": entry["address"],
                         "chain": entry.get("chain", "base")},
                    )
                    planned_units += outcome.price_units
                except ServiceError:
                    probe_failed = True
            for resource_url in services:
                try:
                    outcome = call_paid_endpoint(
                        probe, route_url, {"resource_url": resource_url},
                    )
                    planned_units += outcome.price_units
                except ServiceError:
                    probe_failed = True
            balance_units = usdc_balance_units(probe, account.address)
        if probe_failed:
            planned_units = cap_units  # price the unprobable at the cap
        if balance_units is None:
            out("balance guard: WARNING — could not read the payer's USDC "
                "balance from any public Base RPC; proceeding on the "
                "spend cap alone")
        elif balance_units < planned_units:
            out(f"INSUFFICIENT FUNDS: payer {account.address} holds "
                f"{format_usd(balance_units)} USDC on Base, but this pass "
                f"plans to spend {format_usd(planned_units)} (daily cap "
                f"{format_usd(cap_units)}). Nothing was signed or paid — "
                f"fund the wallet and re-run.")
            return 3
        else:
            out(f"balance guard: payer holds {format_usd(balance_units)} "
                f"USDC on Base; planned spend {format_usd(planned_units)}")

    errors = 0
    would_spend = 0
    spent = 0
    planned: list[int] = []  # prices in call order, for the dry-run cap projection

    _scrub_no_proxy()
    with httpx.Client(timeout=30.0) as http:
        # The payment path is x402-guard (dogfood): every payment
        # below is pre-flighted through its pipeline before anything
        # is signed. The loop's DailySpendCap rides along as the
        # guard's budget, so the guard's own check calls are
        # authorized and recorded against the same daily cap.
        guard_settings = config.get("guard") or {}
        guard = GuardedClient(
            account=account,
            budget=budget,
            http=http,
            config=GuardConfig(
                settled_enabled=settled_on,
                drift_enabled=bool(guard_settings.get("drift_enabled", True)),
                drift_ttl_seconds=float(
                    guard_settings.get("drift_ttl_seconds", 86_400)
                ),
                recheck_url=guard_settings.get("recheck_url", DEFAULT_RECHECK_URL),
                route_verdict_url=route_url,
                store_path=guard_settings.get("store_path", "x402-guard.db"),
                audit_log_path=guard_settings.get(
                    "audit_log_path", "x402-guard-audit.jsonl"
                ),
            ),
        )

        # --- 1. token screening ---------------------------------------------
        for entry in tokens:
            address = entry["address"]
            chain = entry.get("chain", "base")
            label = entry.get("label", address)
            try:
                gres = guard.pay(
                    token_url, {"address": address, "chain": chain}
                )
            except GuardBlocked as blocked:
                gdecision = blocked.decision
                if gdecision.settled_report is not None:
                    out(f"[settled] {token_url}: "
                        f"{gdecision.settled_report.describe()}")
                out(f"[token] {label}: BLOCKED by x402-guard — "
                    f"{'; '.join(gdecision.reasons)}")
                continue
            except ServiceError as exc:
                errors += 1
                out(f"[token] {label} ({address}, {chain}): ERROR {exc}")
                continue
            outcome = gres.outcome
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
            if gres.decision.warnings or (
                outcome.mode == "dry_run" and gres.decision.blocked
            ):
                out(f"        guard: {gres.decision.summary()}")

        # --- 2. new-service checks -------------------------------------------
        for resource_url in services:
            # The guard runs the Settled pre-flight (advisory + the
            # narrow veto) as stage 1 of its pipeline, then — only if
            # the target passes — makes the paid RouteVerdict check.
            try:
                gres = guard.pay_on_behalf(
                    resource_url, route_url, {"resource_url": resource_url}
                )
            except GuardBlocked as blocked:
                gdecision = blocked.decision
                sreport = gdecision.settled_report
                if sreport is not None:
                    out(f"[settled] {resource_url}: {sreport.describe()}")
                    if gdecision.settled_veto:
                        out(f"        Settled hard negative: "
                            f"{gdecision.settled_veto}")
                if gdecision.settled_veto:
                    # Nothing left to ask RouteVerdict: the service
                    # cannot be adopted, and the guard refused before
                    # anything was signed or paid.
                    out(f"[service] {resource_url}: -> PASS (Settled pre-flight "
                        f"veto — RouteVerdict check skipped, nothing paid)")
                else:
                    out(f"[service] {resource_url}: BLOCKED by x402-guard — "
                        f"{'; '.join(gdecision.reasons)}")
                continue
            except ServiceError as exc:
                errors += 1
                out(f"[service] {resource_url}: ERROR {exc}")
                continue
            outcome = gres.outcome
            sreport = gres.decision.settled_report
            veto = gres.decision.settled_veto
            if sreport is not None:
                out(f"[settled] {resource_url}: {sreport.describe()}")
                if veto:
                    out(f"        Settled hard negative: {veto}")
            planned.append(outcome.price_units)
            if outcome.mode == "dry_run":
                would_spend += outcome.price_units
                req = outcome.requirement or {}
                out(f"[service] {resource_url}: DRY-RUN would pay "
                    f"{format_usd(outcome.price_units)} to {req.get('payTo')} on "
                    f"{req.get('network')} for a RouteVerdict trust check")
                out(f"        policy on the check: ADOPT only if TRUSTED and "
                    f"trust score >= {min_trust:g}; otherwise PASS")
                if veto:
                    out(f"        settled note: the hard negative above stands "
                        f"regardless — this service would PASS even on a "
                        f"TRUSTED result")
            elif outcome.mode == "blocked":
                out(f"[service] {resource_url}: BLOCKED by spend cap — {outcome.note}")
            else:
                spent += outcome.price_units
                check = outcome.response or {}
                decision = decide_service(check, min_trust_score=min_trust)
                out(f"[service] {resource_url}: verdict {decision.verdict} "
                    f"trust {decision.score:g} -> {decision.action} ({decision.reason})")
                if sreport is not None and sreport.corroborated:
                    note = ("corroborated by Settled: its scout's test purchase "
                            "of this endpoint delivered as advertised")
                    if decision.action == "ADOPT":
                        note += (" — the adoption stands on RouteVerdict's rule "
                                 "alone; Settled only confirms it")
                    out(f"        {note}")
                tx = (outcome.receipt or {}).get("transaction")
                if tx:
                    out(f"        settlement tx: {tx}")
            if gres.decision.warnings:
                out(f"        guard: {gres.decision.summary()}")

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
    parser.add_argument("--settled", action=argparse.BooleanOptionalAction,
                        default=None,
                        help="Settled pre-flight before each service check "
                             "(default: on; --no-settled disables; the "
                             "SETTLED_CHECK env var and the config's "
                             "settled_check key also set it)")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot load config {args.config}: {exc}", file=sys.stderr)
        return 2
    return run_pass(config, live=args.live, settled=args.settled)


if __name__ == "__main__":
    raise SystemExit(main())
