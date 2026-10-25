"""Settled pre-flight — the MCP client and the report policy.

Offline: an httpx MockTransport plays Settled's free MCP endpoint.
The payload fixtures are real settled_check responses captured from
the live free tier on 2026-10-24, trimmed to the fields the parser
reads (see each fixture's _comment) — except the failed-delivery
fixture, which is constructed (its shape mirrors the real receipt with
the outcome flipped) because no live endpoint returns one today.

Policy under test: corroboration is annotation-only, the veto is
narrow (explicit negative records only), and every failure mode —
unknown endpoint, outage, timeout, protocol garbage — degrades to
"proceed without Settled", never to a crash or a block.
"""

import json
from pathlib import Path

import httpx

from verdict_loop.settled_check import SettledReport, fetch_settled_report

FIXTURES = Path(__file__).parent / "fixtures"
VERIFIED_URL = "https://stall-row-production.up.railway.app/v1/page-to-markdown"
TOKEN_URL = "https://token-verdict-production.up.railway.app/v1/verdict"
UNKNOWN_URL = "https://nonexistent-example-xyz.example/v1/paid"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def rpc_result(payload: dict, *, structured: bool = True) -> dict:
    result = {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "isError": False,
    }
    if structured:
        result["structuredContent"] = payload
    return result


class FakeSettledMcp:
    """Plays the free MCP endpoint: initialize -> initialized -> tools/call.

    payloads maps endpoint URL -> settled_check payload dict. fail is
    one of None | "connect" | "timeout" | "http500" | "tool_error".
    """

    def __init__(self, payloads: dict, *, fail: str | None = None, sse: bool = False):
        self.payloads = payloads
        self.fail = fail
        self.sse = sse
        self.tool_calls = 0

    def _reply(self, request: httpx.Request, message: dict) -> httpx.Response:
        if self.sse:
            body = "data: " + json.dumps(message) + "\n\n"
            return httpx.Response(
                200, content=body, headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=message)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.fail == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if self.fail == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        body = json.loads(request.content)
        method = body.get("method")
        if method == "initialize":
            return self._reply(request, {
                "jsonrpc": "2.0", "id": body["id"],
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-settled", "version": "0"},
                },
            })
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            self.tool_calls += 1
            if self.fail == "http500":
                return httpx.Response(500, text="boom")
            assert body["params"]["name"] == "settled_check"
            url = body["params"]["arguments"]["url"]
            if self.fail == "tool_error":
                result = {"content": [{"type": "text", "text": "nope"}],
                          "isError": True}
            else:
                result = rpc_result(self.payloads[url])
            return self._reply(request, {"jsonrpc": "2.0", "id": body["id"],
                                         "result": result})
        raise AssertionError(f"unexpected MCP method: {method}")


def client_for(fake: FakeSettledMcp) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake))


def fetch(fake: FakeSettledMcp, url: str) -> SettledReport:
    with client_for(fake) as http:
        return fetch_settled_report(http, url)


# --- the captured records ---------------------------------------------------------

def test_verified_record_corroborates_without_veto():
    report = fetch(FakeSettledMcp({VERIFIED_URL: load("settled_check_verified.json")}),
                   VERIFIED_URL)
    assert report.available and report.found
    assert report.corroborated is True
    assert report.hard_negative is None
    assert report.quality_total == 79
    assert report.delivery_verified is True
    assert report.receipt_delivered is True
    assert report.receipt_verdict == "as_advertised"
    assert "VERIFIED" in report.describe()


def test_known_but_untested_record_is_neutral():
    report = fetch(FakeSettledMcp({TOKEN_URL: load("settled_check_known_untested.json")}),
                   TOKEN_URL)
    assert report.available and report.found
    assert report.corroborated is False      # never test-bought: no stamp
    assert report.hard_negative is None      # and nothing negative either
    assert report.delivery_verified is None


def test_unknown_endpoint_proceeds_unchanged():
    report = fetch(FakeSettledMcp({UNKNOWN_URL: load("settled_check_unknown.json")}),
                   UNKNOWN_URL)
    assert report.available
    assert report.found is False
    assert report.corroborated is False
    assert report.hard_negative is None


# --- the veto ---------------------------------------------------------------------

def test_failed_delivery_receipt_vetoes():
    payload = load("settled_check_failed_delivery.json")
    report = fetch(FakeSettledMcp({payload["url"]: payload}), payload["url"])
    assert report.available and report.found
    assert report.corroborated is False
    assert report.hard_negative is not None
    assert "delivered=false" in report.hard_negative


def test_receipt_comparison_verdict_alone_never_vetoes():
    # A comparison verdict grades the listing's sample, not the
    # delivery: with the purchase delivered, no receipt verdict —
    # fields_missing included — is a hard negative.
    payload = load("settled_check_verified.json")
    payload["delivery_receipt"]["checks"]["verdict"] = "fields_missing"
    payload["delivery_receipt"]["checks"]["as_advertised"] = False
    report = SettledReport.from_payload(VERIFIED_URL, payload)
    assert report.receipt_delivered is True
    assert report.hard_negative is None


def test_nothing_to_compare_with_verified_delivery_does_not_veto():
    # The live Token Verdict record (2026-10-25): delivery_verified,
    # quality 82, delivered receipt — but Settled's listing copy has
    # no usable sample, so the receipt verdict is nothing_to_compare.
    # That must corroborate-and-note, never veto.
    payload = load("settled_check_verified.json")
    payload["delivery_receipt"]["checks"] = {
        "verdict": "nothing_to_compare",
        "as_advertised": None,
        "fields": None,
        "notes": ["the listing has no sample response to compare against"],
    }
    report = SettledReport.from_payload(TOKEN_URL, payload)
    assert report.available and report.found
    assert report.delivery_verified is True
    assert report.receipt_delivered is True
    assert report.receipt_verdict == "nothing_to_compare"
    assert report.nothing_to_compare is True
    assert report.corroborated is True
    assert report.hard_negative is None
    described = report.describe()
    assert "nothing to compare" in described
    assert "proceeding on verified delivery" in described


def test_nothing_to_compare_without_verified_delivery_passes_through():
    # No verified delivery + nothing_to_compare: neither a
    # corroboration nor a veto — the pass proceeds on RouteVerdict
    # alone, exactly like an untested endpoint.
    payload = load("settled_check_verified.json")
    payload["delivery_verified"] = False
    payload["delivery_receipt"]["checks"] = {
        "verdict": "nothing_to_compare",
        "as_advertised": None,
        "fields": None,
        "notes": ["the listing has no sample response to compare against"],
    }
    report = SettledReport.from_payload(TOKEN_URL, payload)
    assert report.nothing_to_compare is True
    assert report.corroborated is False
    assert report.hard_negative is None
    assert "not a delivery failure" in report.describe()


def test_explicit_not_payable_verdict_vetoes():
    # The branch accepts any explicit negative verdict string verbatim;
    # the known non-negative values (payable / delivered / unknown) are
    # covered by the captured-fixture tests above.
    payload = load("settled_check_known_untested.json")
    payload["payability"]["verdict"] = "not_payable"
    report = SettledReport.from_payload(TOKEN_URL, payload)
    assert report.hard_negative is not None
    assert "not_payable" in report.hard_negative


def test_delivery_verified_false_alone_does_not_veto():
    # A false flag with no receipt and a payable verdict is ambiguous
    # (Settled's own feed showed false for never-purchased routes), so
    # the veto stays narrow: explicit records only.
    payload = load("settled_check_known_untested.json")
    payload["delivery_verified"] = False
    report = SettledReport.from_payload(TOKEN_URL, payload)
    assert report.hard_negative is None
    assert report.corroborated is False


# --- degradation: Settled must never crash or block the loop ----------------------

def test_connect_error_degrades_to_unavailable():
    report = fetch(FakeSettledMcp({}, fail="connect"), TOKEN_URL)
    assert report.available is False
    assert report.warning
    assert report.hard_negative is None
    assert report.corroborated is False
    assert "unavailable" in report.describe()


def test_timeout_degrades_to_unavailable():
    report = fetch(FakeSettledMcp({}, fail="timeout"), TOKEN_URL)
    assert report.available is False
    assert report.warning


def test_http_500_degrades_to_unavailable():
    report = fetch(FakeSettledMcp({}, fail="http500"), TOKEN_URL)
    assert report.available is False
    assert "500" in report.warning


def test_tool_error_result_degrades_to_unavailable():
    report = fetch(FakeSettledMcp({}, fail="tool_error"), TOKEN_URL)
    assert report.available is False


def test_sse_framing_is_parsed():
    fake = FakeSettledMcp({VERIFIED_URL: load("settled_check_verified.json")}, sse=True)
    report = fetch(fake, VERIFIED_URL)
    assert report.available and report.corroborated


def test_text_only_result_is_parsed():
    # Some MCP servers return only the text content, no structuredContent.
    payload = load("settled_check_verified.json")

    class TextOnlyMcp(FakeSettledMcp):
        def __call__(self, request):
            body = json.loads(request.content)
            if body.get("method") == "tools/call":
                self.tool_calls += 1
                return httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": body["id"],
                    "result": rpc_result(payload, structured=False),
                })
            return super().__call__(request)

    report = fetch(TextOnlyMcp({}), VERIFIED_URL)
    assert report.available and report.corroborated
