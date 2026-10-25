"""x402-guard integration: the loop's payments run THROUGH the guard.

Offline: one MockTransport plays Settled (unknown), StallRow Recheck
(the guard's drift stage), RouteVerdict, Token Verdict, and Base
JSON-RPC balance reads. The properties under test:

- a live pass pays its Recheck drift check and its RouteVerdict check
  through the guard, records both against the one daily budget, and
  leaves the guard's audit log + cache behind as evidence,
- a drift block (payTo moved) stops the service payment before the
  RouteVerdict call is ever paid,
- a second pass inside the drift TTL makes NO second Recheck call —
  the guard's cache is what executes,
- token screening payments run through the guard too (a Recheck look
  at the Token Verdict endpoint precedes the first screening call).
"""

import base64
import json
from pathlib import Path

import httpx
from eth_account import Account

from verdict_loop.budget import DailySpendCap
from verdict_loop.loop import run_pass

FIXTURES = Path(__file__).parent / "fixtures"
ROUTE_URL = "https://route-verdict-production.up.railway.app/v1/check"
TOKEN_URL = "https://token-verdict-production.up.railway.app/v1/verdict"
TARGET = TOKEN_URL
PAY_TO = "0x097f9685D1e0752bF8B02d61E5Ce9be7eA0FBA7F"
PAY_TO_MOVED = "0x2222222222222222222222222222222222222222"
WETH = "0x4200000000000000000000000000000000000006"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def challenge_header(amount: str) -> str:
    challenge = load("route_verdict_402_challenge.json")
    challenge["accepts"][0]["amount"] = amount
    return base64.b64encode(json.dumps(challenge).encode()).decode()


class FakeSettledMcp:
    """Settled knows nothing about any URL — no veto, no corroboration."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body["id"],
                "result": {"protocolVersion": "2025-06-18",
                           "capabilities": {"tools": {}}},
            })
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            payload = load("settled_check_unknown.json")
            payload["url"] = body["params"]["arguments"]["url"]
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body["id"],
                "result": {"content": [{"type": "text",
                                        "text": json.dumps(payload)}],
                           "structuredContent": payload, "isError": False},
            })
        raise AssertionError(f"unexpected MCP method: {method}")


class FakeRecheck:
    """StallRow /v1/recheck: 402 ($0.005) until paid, then the
    scripted drift answer. Counts paid calls."""

    def __init__(self, payload=None):
        self.paid_attempts = 0
        self.challenge = challenge_header("5000")
        self.payload = payload or {
            "watch_id": "w", "url": TARGET, "kind": "x402",
            "status": "BASELINE", "changes": [],
            "current": {"amount": "20000", "payTo": PAY_TO},
            "checked_at": "2026-10-25T00:00:00Z", "summary": "baseline",
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("PAYMENT-SIGNATURE"):
            self.paid_attempts += 1
            return httpx.Response(200, json=self.payload)
        return httpx.Response(402, headers={"payment-required": self.challenge})


class FakePaidService:
    """402 until paid, then a fixed JSON payload. Counts paid calls."""

    def __init__(self, amount: str, payload: dict):
        self.paid_attempts = 0
        self.challenge = challenge_header(amount)
        self.payload = payload

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("PAYMENT-SIGNATURE"):
            self.paid_attempts += 1
            receipt = base64.b64encode(json.dumps(
                {"success": True, "transaction": "0xfeedface"}
            ).encode()).decode()
            return httpx.Response(
                200, json=self.payload, headers={"payment-response": receipt}
            )
        return httpx.Response(402, headers={"payment-required": self.challenge})


class Router:
    def __init__(self, *, recheck=None):
        self.settled = FakeSettledMcp()
        self.recheck = recheck or FakeRecheck()
        self.route = FakePaidService("50000", {"verdict": "TRUSTED", "score": 85.0})
        self.token = FakePaidService("20000", {
            "verdict": "SOLID", "score": 10.0,
            "token": {"symbol": "WETH"}, "take": "deep liquidity",
        })

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "settled.tools":
            return self.settled(request)
        if host == "stall-row-production.up.railway.app":
            return self.recheck(request)
        try:
            body = json.loads(request.content)
        except ValueError:
            body = {}
        if body.get("method") == "eth_call":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body.get("id", 1),
                "result": hex(10_000_000),  # $10 — plenty for a pass
            })
        if host == "token-verdict-production.up.railway.app":
            return self.token(request)
        return self.route(request)


def make_config(tmp_path, *, tokens=None, services=None, budget_name="budget.json"):
    return {
        "tokens": tokens if tokens is not None else [],
        "services_to_check": services if services is not None else [TARGET],
        "route_verdict_url": ROUTE_URL,
        "token_verdict_url": TOKEN_URL,
        "daily_cap_usd": 0.10,
        "budget_state": str(tmp_path / budget_name),
        "guard": {
            "store_path": str(tmp_path / "guard.db"),
            "audit_log_path": str(tmp_path / "guard-audit.jsonl"),
        },
    }


def run_live(tmp_path, monkeypatch, router, config):
    monkeypatch.setenv("AGENT_PRIVATE_KEY", Account.create().key.hex())
    monkeypatch.delenv("SETTLED_CHECK", raising=False)
    lines: list[str] = []
    import verdict_loop.loop as loop_module

    real_client = loop_module.httpx.Client

    def mock_client(*args, **kw):
        return real_client(transport=httpx.MockTransport(router))

    monkeypatch.setattr(loop_module.httpx, "Client", mock_client)
    code = run_pass(config, live=True, out=lines.append)
    return code, "\n".join(lines)


def read_audit(tmp_path):
    path = tmp_path / "guard-audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_live_pass_executes_through_the_guard(tmp_path, monkeypatch):
    router = Router()
    code, text = run_live(tmp_path, monkeypatch, router, make_config(tmp_path))
    assert code == 0
    assert "-> ADOPT" in text
    # The guard's drift stage paid Recheck exactly once; the loop paid
    # RouteVerdict exactly once. Both settled against the one budget.
    assert router.recheck.paid_attempts == 1
    assert router.route.paid_attempts == 1
    cap = DailySpendCap(100_000, state_path=tmp_path / "budget.json")
    assert cap.spent_units == 55_000
    # Evidence the guard ran: its cache + audit log exist, and the
    # audit entry names the drift stage and what it cost.
    assert (tmp_path / "guard.db").exists()
    entries = read_audit(tmp_path)
    assert entries, "guard audit log is empty"
    entry = entries[-1]
    assert entry["pay_url"] == ROUTE_URL
    assert entry["check_cost_units"] == 5_000
    assert [s["name"] for s in entry["stages"]] == [
        "settled", "drift", "route_verdict", "caps",
    ]


def test_guard_drift_block_stops_the_service_payment(tmp_path, monkeypatch):
    moved = FakeRecheck(payload={
        "watch_id": "w", "url": TARGET, "kind": "x402",
        "status": "CHANGED",
        "changes": [{"field": "payTo", "before": PAY_TO, "after": PAY_TO_MOVED}],
        "current": {"amount": "20000", "payTo": PAY_TO_MOVED},
        "checked_at": "2026-10-25T00:00:00Z", "summary": "payTo changed",
    })
    router = Router(recheck=moved)
    code, text = run_live(tmp_path, monkeypatch, router, make_config(tmp_path))
    assert code == 0  # a policy block is not a run error
    assert "BLOCKED by x402-guard" in text
    assert "payTo changed" in text
    assert router.route.paid_attempts == 0  # the check was never paid
    cap = DailySpendCap(100_000, state_path=tmp_path / "budget.json")
    assert cap.spent_units == 5_000  # only the Recheck look itself


def test_second_pass_reuses_the_guards_cached_drift_check(tmp_path, monkeypatch):
    router = Router()
    code1, _ = run_live(
        tmp_path, monkeypatch, router,
        make_config(tmp_path, budget_name="budget-1.json"),
    )
    code2, text2 = run_live(
        tmp_path, monkeypatch, router,
        make_config(tmp_path, budget_name="budget-2.json"),
    )
    assert code1 == 0 and code2 == 0
    assert "-> ADOPT" in text2
    # One Recheck payment across both passes: the second pass's drift
    # stage was served by the guard's local cache (24h TTL).
    assert router.recheck.paid_attempts == 1
    assert router.route.paid_attempts == 2


def test_cap_stop_skips_the_service_check_and_still_completes(
        tmp_path, monkeypatch):
    """The 2026-10-25 08:00 failure, as a regression: an earlier pass
    the same UTC day had already settled $0.04, so after this pass's
    token screens ($0.04) + cold-cache Recheck ($0.005) only $0.015 of
    the cap remained — not enough for the $0.05 service check. The
    pass must degrade in order (optional service check skipped first,
    token screens untouched), print a cap stop, produce its summary,
    and exit 0 — not crash inside the guard."""
    DailySpendCap(100_000, state_path=tmp_path / "budget.json").record(
        40_000, label="earlier pass today")
    router = Router()
    config = make_config(
        tmp_path,
        tokens=[
            {"address": WETH, "chain": "base",
             "label": "Wrapped Ether (Base)"},
            {"address": "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
             "chain": "base", "label": "Aerodrome AERO (Base)"},
        ],
        services=[TARGET],
    )
    code, text = run_live(tmp_path, monkeypatch, router, config)
    assert code == 0  # a policy stop completes; it is not a failure
    assert "cap stop:" in text
    assert "optional service check skipped" in text
    # Both token screens settled; the drift look ran once; the
    # service check was never paid.
    assert router.token.paid_attempts == 2
    assert router.recheck.paid_attempts == 1
    assert router.route.paid_attempts == 0
    cap = DailySpendCap(100_000, state_path=tmp_path / "budget.json")
    assert cap.spent_units == 85_000
    # The summary's pass spend is the ledger delta — guard check
    # spend included ($0.045), not just the token prices ($0.04).
    assert "spent this pass: $0.045" in text
    assert "spent today: $0.085" in text


def test_fresh_day_full_pass_fits_the_cap(tmp_path, monkeypatch):
    """Cap sizing: on a fresh day a full pass — two token screens, a
    cold-cache Recheck, and the service check — costs $0.095 and
    fits the $0.10 cap whole, with no cap stop."""
    router = Router()
    config = make_config(
        tmp_path,
        tokens=[
            {"address": WETH, "chain": "base",
             "label": "Wrapped Ether (Base)"},
            {"address": "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
             "chain": "base", "label": "Aerodrome AERO (Base)"},
        ],
        services=[TARGET],
    )
    code, text = run_live(tmp_path, monkeypatch, router, config)
    assert code == 0
    assert "-> ADOPT" in text
    assert "cap stop:" not in text
    cap = DailySpendCap(100_000, state_path=tmp_path / "budget.json")
    assert cap.spent_units == 95_000


def test_token_screening_runs_through_the_guard(tmp_path, monkeypatch):
    router = Router()
    config = make_config(
        tmp_path,
        tokens=[{"address": WETH, "chain": "base", "label": "Wrapped Ether (Base)"}],
        services=[],
    )
    code, text = run_live(tmp_path, monkeypatch, router, config)
    assert code == 0
    assert "WOULD_BUY" in text
    assert router.token.paid_attempts == 1
    # The guard vetted the Token Verdict endpoint (drift look) before
    # the screening payment — the guard is the token path too.
    assert router.recheck.paid_attempts == 1
    entries = read_audit(tmp_path)
    assert any(e["pay_url"] == TOKEN_URL for e in entries)
