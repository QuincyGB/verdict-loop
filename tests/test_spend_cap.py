"""Spend-cap enforcement — the live-mode safety rail.

Covers the ledger itself (authorize/record/persist/day rollover) and
the full client flow against an httpx MockTransport playing the real
captured Token Verdict challenge: the cap must refuse a payment BEFORE
anything is signed, a dry run must never spend, and settled payments
must be recorded exactly once.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from eth_account import Account

from verdict_loop.budget import DailySpendCap
from verdict_loop.x402 import SpendCapExceeded, call_paid_endpoint

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://token-verdict-production.up.railway.app/v1/verdict"
BODY = {"address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "chain": "base"}


def challenge_header() -> str:
    challenge = json.loads(
        (FIXTURES / "token_verdict_402_challenge.json").read_text(encoding="utf-8")
    )
    return base64.b64encode(json.dumps(challenge).encode()).decode()


class FakeService:
    """Plays the endpoint: 402 until a PAYMENT-SIGNATURE arrives, then 200."""

    def __init__(self):
        self.paid_attempts = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("PAYMENT-SIGNATURE"):
            self.paid_attempts += 1
            receipt = base64.b64encode(json.dumps(
                {"success": True, "transaction": "0xdeadbeef"}
            ).encode()).decode()
            return httpx.Response(
                200,
                json={"verdict": "SOLID", "score": 10.0},
                headers={"payment-response": receipt},
            )
        return httpx.Response(402, headers={"payment-required": challenge_header()})


def client_for(service: FakeService) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(service))


# --- the ledger ------------------------------------------------------------------

def test_authorize_and_record(tmp_path):
    cap = DailySpendCap(100_000, state_path=tmp_path / "budget.json")
    cap.authorize(20_000)
    cap.record(20_000, label="a")
    cap.record(50_000, label="b")
    assert cap.spent_units == 70_000
    assert cap.remaining_units == 30_000
    cap.authorize(30_000)  # exactly at the cap: allowed
    with pytest.raises(SpendCapExceeded):
        cap.authorize(30_001)


def test_record_may_not_break_the_cap(tmp_path):
    cap = DailySpendCap(25_000, state_path=tmp_path / "budget.json")
    with pytest.raises(SpendCapExceeded):
        cap.record(25_001)


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "budget.json"
    DailySpendCap(100_000, state_path=path).record(20_000, label="x")
    reloaded = DailySpendCap(100_000, state_path=path)
    assert reloaded.spent_units == 20_000


def test_new_day_resets_the_ledger(tmp_path):
    path = tmp_path / "budget.json"
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    old = DailySpendCap(100_000, state_path=path, now=yesterday)
    old.record(90_000, label="yesterday")
    today = DailySpendCap(100_000, state_path=path)
    assert today.spent_units == 0
    assert today.remaining_units == 100_000


def test_default_cap_is_ten_cents():
    assert DailySpendCap().cap_units == 100_000


# --- the client flow against the cap ----------------------------------------------

def test_dry_run_never_spends(tmp_path):
    service = FakeService()
    cap = DailySpendCap(100_000, state_path=tmp_path / "budget.json")
    with client_for(service) as http:
        outcome = call_paid_endpoint(http, URL, BODY, account=None, budget=cap)
    assert outcome.mode == "dry_run"
    assert outcome.price_units == 20_000
    assert outcome.response is None  # a dry run NEVER invents a verdict
    assert service.paid_attempts == 0
    assert cap.spent_units == 0


def test_live_calls_record_spend_exactly(tmp_path):
    service = FakeService()
    cap = DailySpendCap(100_000, state_path=tmp_path / "budget.json")
    account = Account.create()  # test signer, generated at run time
    with client_for(service) as http:
        first = call_paid_endpoint(http, URL, BODY, account=account, budget=cap)
        second = call_paid_endpoint(http, URL, BODY, account=account, budget=cap)
    assert first.mode == second.mode == "paid"
    assert first.response["verdict"] == "SOLID"
    assert first.receipt["transaction"] == "0xdeadbeef"
    assert service.paid_attempts == 2
    assert cap.spent_units == 40_000


def test_cap_blocks_before_signing(tmp_path):
    service = FakeService()
    cap = DailySpendCap(30_000, state_path=tmp_path / "budget.json")  # fits ONE call
    account = Account.create()
    with client_for(service) as http:
        first = call_paid_endpoint(http, URL, BODY, account=account, budget=cap)
        second = call_paid_endpoint(http, URL, BODY, account=account, budget=cap)
    assert first.mode == "paid"
    assert second.mode == "blocked"
    assert second.response is None
    # The refusal happened before signing: the service saw exactly one
    # paid attempt, and the ledger holds exactly one payment.
    assert service.paid_attempts == 1
    assert cap.spent_units == 20_000
