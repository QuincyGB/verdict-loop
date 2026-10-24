"""Settled pre-flight inside a full loop pass.

Offline: one MockTransport routes both hosts — the RouteVerdict
endpoint (real captured 402 challenge, then a paid TRUSTED 85 answer)
and Settled's free MCP endpoint. The properties under test:

- corroboration annotates an ADOPT but never creates one,
- a Settled hard negative vetoes adoption — in live mode the paid
  RouteVerdict check is not even attempted,
- unknown endpoint / Settled outage: the pass proceeds exactly as
  the pre-pre-flight loop did,
- dry-run reports the pre-flight and still cannot spend.
"""

import base64
import json
from pathlib import Path

import httpx
import pytest
from eth_account import Account

from verdict_loop.budget import DailySpendCap
from verdict_loop.loop import run_pass

FIXTURES = Path(__file__).parent / "fixtures"
ROUTE_URL = "https://route-verdict-production.up.railway.app/v1/check"
TARGET = "https://token-verdict-production.up.railway.app/v1/verdict"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def settled_payload(fixture: str) -> dict:
    payload = load(fixture)
    payload["url"] = TARGET
    return payload


class FakeSettledMcp:
    """Minimal play of Settled's free MCP endpoint (same shape as the
    fuller fake in test_settled_check.py; kept local so this file is
    self-contained like the other suites)."""

    def __init__(self, payloads: dict):
        self.payloads = payloads
        self.tool_calls = 0

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
            self.tool_calls += 1
            payload = self.payloads[body["params"]["arguments"]["url"]]
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body["id"],
                "result": {"content": [{"type": "text",
                                        "text": json.dumps(payload)}],
                           "structuredContent": payload, "isError": False},
            })
        raise AssertionError(f"unexpected MCP method: {method}")


class FakeRouteService:
    """402 until a PAYMENT-SIGNATURE arrives, then TRUSTED 85."""

    def __init__(self):
        self.paid_attempts = 0
        challenge = load("route_verdict_402_challenge.json")
        self.challenge_header = base64.b64encode(
            json.dumps(challenge).encode()
        ).decode()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("PAYMENT-SIGNATURE"):
            self.paid_attempts += 1
            receipt = base64.b64encode(json.dumps(
                {"success": True, "transaction": "0xfeedface"}
            ).encode()).decode()
            return httpx.Response(
                200,
                json={"verdict": "TRUSTED", "score": 85.0},
                headers={"payment-response": receipt},
            )
        return httpx.Response(402, headers={"payment-required": self.challenge_header})


class Router:
    """Dispatches by host; optionally takes Settled down entirely."""

    def __init__(self, route_service, settled_fake, *, settled_down=False):
        self.route_service = route_service
        self.settled_fake = settled_fake
        self.settled_down = settled_down

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "settled.tools":
            if self.settled_down:
                raise httpx.ConnectError("settled unreachable", request=request)
            return self.settled_fake(request)
        return self.route_service(request)


def make_config(tmp_path) -> dict:
    return {
        "tokens": [],
        "services_to_check": [TARGET],
        "route_verdict_url": ROUTE_URL,
        "daily_cap_usd": 0.10,
        "budget_state": str(tmp_path / "budget.json"),
    }


def run_live(tmp_path, monkeypatch, router, **kwargs):
    monkeypatch.setenv("AGENT_PRIVATE_KEY", Account.create().key.hex())
    monkeypatch.delenv("SETTLED_CHECK", raising=False)
    lines: list[str] = []
    # loop.run_pass creates its own httpx.Client; swap in the mock by
    # patching the Client class it uses for the duration of the pass.
    import verdict_loop.loop as loop_module

    real_client = loop_module.httpx.Client

    def mock_client(*args, **kw):
        return real_client(transport=httpx.MockTransport(router))

    monkeypatch.setattr(loop_module.httpx, "Client", mock_client)
    code = run_pass(make_config(tmp_path), live=True, out=lines.append, **kwargs)
    return code, "\n".join(lines)


# --- live mode ----------------------------------------------------------------------

def test_adopt_with_settled_corroboration(tmp_path, monkeypatch):
    route = FakeRouteService()
    settled = FakeSettledMcp({TARGET: settled_payload("settled_check_verified.json")})
    code, text = run_live(tmp_path, monkeypatch, Router(route, settled))
    assert code == 0
    assert "-> ADOPT" in text
    assert "corroborated by Settled" in text
    assert route.paid_attempts == 1
    cap = DailySpendCap(100_000, state_path=tmp_path / "budget.json")
    assert cap.spent_units == 50_000  # only the RouteVerdict check; Settled is free


def test_settled_veto_skips_the_paid_check(tmp_path, monkeypatch):
    route = FakeRouteService()
    settled = FakeSettledMcp({TARGET: settled_payload("settled_check_failed_delivery.json")})
    code, text = run_live(tmp_path, monkeypatch, Router(route, settled))
    assert code == 0
    assert "Settled pre-flight" in text and "veto" in text
    assert "-> PASS (Settled pre-flight veto" in text
    assert route.paid_attempts == 0  # the paid check was never attempted
    cap = DailySpendCap(100_000, state_path=tmp_path / "budget.json")
    assert cap.spent_units == 0


def test_unknown_endpoint_adopts_as_before(tmp_path, monkeypatch):
    route = FakeRouteService()
    settled = FakeSettledMcp({TARGET: settled_payload("settled_check_unknown.json")})
    code, text = run_live(tmp_path, monkeypatch, Router(route, settled))
    assert code == 0
    assert "-> ADOPT" in text
    assert "no payability verdict or delivery record" in text
    assert "corroborated" not in text
    assert route.paid_attempts == 1


def test_settled_outage_never_blocks_the_pass(tmp_path, monkeypatch):
    route = FakeRouteService()
    router = Router(route, FakeSettledMcp({}), settled_down=True)
    code, text = run_live(tmp_path, monkeypatch, router)
    assert code == 0
    assert "pre-flight unavailable" in text
    assert "-> ADOPT" in text
    assert route.paid_attempts == 1


def test_preflight_disabled_makes_no_settled_calls(tmp_path, monkeypatch):
    route = FakeRouteService()
    settled = FakeSettledMcp({TARGET: settled_payload("settled_check_verified.json")})
    code, text = run_live(tmp_path, monkeypatch, Router(route, settled), settled=False)
    assert code == 0
    assert settled.tool_calls == 0
    assert "[settled]" not in text
    assert "-> ADOPT" in text


# --- dry-run ------------------------------------------------------------------------

def test_dry_run_reports_preflight_and_spends_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("SETTLED_CHECK", raising=False)
    route = FakeRouteService()
    settled = FakeSettledMcp({TARGET: settled_payload("settled_check_verified.json")})
    router = Router(route, settled)
    lines: list[str] = []
    import verdict_loop.loop as loop_module

    real_client = loop_module.httpx.Client

    def mock_client(*args, **kw):
        return real_client(transport=httpx.MockTransport(router))

    monkeypatch.setattr(loop_module.httpx, "Client", mock_client)
    code = run_pass(make_config(tmp_path), live=False, out=lines.append)
    text = "\n".join(lines)
    assert code == 0
    assert "[settled]" in text and "delivery VERIFIED" in text
    assert "DRY-RUN would pay $0.05" in text
    assert route.paid_attempts == 0
