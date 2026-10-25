"""Live-mode balance guard.

Offline: a MockTransport plays the RouteVerdict endpoint (real
captured 402 challenge, then a paid TRUSTED 85 answer), Settled's free
MCP endpoint, and Base JSON-RPC `eth_call` balance reads. Properties:

- a payer balance that reads fine and covers the planned spend lets
  the pass proceed exactly as before,
- a KNOWN balance below the planned spend stops the run cleanly with
  exit code 3 and INSUFFICIENT FUNDS — before anything is signed,
- an unreadable balance (RPC error/garbage) only warns; the spend cap
  still bounds the pass,
- the balance reader itself parses hex results and shrugs off bad
  endpoints.
"""

import base64
import json
from pathlib import Path

import httpx
from eth_account import Account

from verdict_loop.loop import run_pass
from verdict_loop.wallet import usdc_balance_units

FIXTURES = Path(__file__).parent / "fixtures"
ROUTE_URL = "https://route-verdict-production.up.railway.app/v1/check"
TARGET = "https://token-verdict-production.up.railway.app/v1/verdict"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeSettledMcp:
    """Settled knows nothing about the target — no veto, no corroboration."""

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
    """eth_call -> the balance fake; settled.tools -> Settled; else the
    RouteVerdict fake. balance_units=None plays a broken RPC."""

    def __init__(self, route_service, *, balance_units):
        self.route_service = route_service
        self.settled = FakeSettledMcp()
        self.balance_units = balance_units

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "settled.tools":
            return self.settled(request)
        try:
            body = json.loads(request.content)
        except ValueError:
            body = {}
        if body.get("method") == "eth_call":
            if self.balance_units is None:
                return httpx.Response(500, json={"error": "rpc down"})
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body.get("id", 1),
                "result": hex(self.balance_units),
            })
        return self.route_service(request)


def make_config(tmp_path) -> dict:
    return {
        "tokens": [],
        "services_to_check": [TARGET],
        "route_verdict_url": ROUTE_URL,
        "daily_cap_usd": 0.10,
        "budget_state": str(tmp_path / "budget.json"),
    }


def run_live(tmp_path, monkeypatch, router):
    monkeypatch.setenv("AGENT_PRIVATE_KEY", Account.create().key.hex())
    monkeypatch.delenv("SETTLED_CHECK", raising=False)
    lines: list[str] = []
    import verdict_loop.loop as loop_module

    real_client = loop_module.httpx.Client

    def mock_client(*args, **kw):
        return real_client(transport=httpx.MockTransport(router))

    monkeypatch.setattr(loop_module.httpx, "Client", mock_client)
    code = run_pass(make_config(tmp_path), live=True, out=lines.append)
    return code, "\n".join(lines)


# --- the reader -----------------------------------------------------------------

def test_balance_reader_parses_hex_result():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "eth_call"
        assert body["params"][0]["data"].startswith("0x70a08231")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                         "result": hex(731_957)})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert usdc_balance_units(http, "0xa4f183a6799F0310FcCC545B07F2DcC960223de2",
                                  rpc_urls=("https://rpc.example",)) == 731_957


def test_balance_reader_falls_through_bad_endpoints():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="nope")
        if calls["n"] == 2:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                             "error": {"code": -32000}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                         "result": "0x10"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        got = usdc_balance_units(http, "0x0000000000000000000000000000000000000001",
                                 rpc_urls=("https://a", "https://b", "https://c"))
        assert got == 16


def test_balance_reader_returns_none_when_all_fail():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert usdc_balance_units(http, "0x0000000000000000000000000000000000000001",
                                  rpc_urls=("https://a",)) is None


# --- the guard inside a live pass -------------------------------------------------

def test_insufficient_funds_stops_before_signing(tmp_path, monkeypatch):
    route = FakeRouteService()
    # $0.04 known balance vs the $0.05 RouteVerdict check.
    router = Router(route, balance_units=40_000)
    code, text = run_live(tmp_path, monkeypatch, router)
    assert code == 3
    assert "INSUFFICIENT FUNDS" in text
    assert route.paid_attempts == 0
    assert not (tmp_path / "budget.json").exists()


def test_sufficient_balance_proceeds(tmp_path, monkeypatch):
    route = FakeRouteService()
    router = Router(route, balance_units=60_000)
    code, text = run_live(tmp_path, monkeypatch, router)
    assert code == 0
    assert "balance guard: payer holds $0.06" in text
    assert "-> ADOPT" in text
    assert route.paid_attempts == 1


def test_unreadable_balance_warns_and_proceeds(tmp_path, monkeypatch):
    route = FakeRouteService()
    router = Router(route, balance_units=None)
    code, text = run_live(tmp_path, monkeypatch, router)
    assert code == 0
    assert "balance guard: WARNING" in text
    assert "-> ADOPT" in text
    assert route.paid_attempts == 1
