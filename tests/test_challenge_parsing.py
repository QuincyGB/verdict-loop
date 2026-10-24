"""402-challenge parsing against REAL challenges captured from the live
production services (2026-10-24, unpaid POSTs — see the fixtures).

Offline: no network is touched anywhere in this suite.
"""

import base64
import json
from pathlib import Path

import httpx
import pytest

from verdict_loop.x402 import parse_payment_required, select_requirement

FIXTURES = Path(__file__).parent / "fixtures"
FLEET_PAY_TO = "0x097f9685D1e0752bF8B02d61E5Ce9be7eA0FBA7F"
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def load_challenge(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def response_with_header(challenge: dict) -> httpx.Response:
    header = base64.b64encode(json.dumps(challenge).encode()).decode()
    return httpx.Response(402, headers={"payment-required": header})


@pytest.mark.parametrize(
    "fixture, expected_amount, expected_url",
    [
        ("token_verdict_402_challenge.json", "20000",
         "https://token-verdict-production.up.railway.app/v1/verdict"),
        ("route_verdict_402_challenge.json", "50000",
         "https://route-verdict-production.up.railway.app/v1/check"),
    ],
)
def test_parse_real_challenge_from_header(fixture, expected_amount, expected_url):
    challenge = load_challenge(fixture)
    parsed = parse_payment_required(response_with_header(challenge))
    assert parsed["x402Version"] == 2
    assert parsed["resource"]["url"] == expected_url

    req = select_requirement(parsed)
    assert req["scheme"] == "exact"
    assert req["network"] == "eip155:8453"
    assert req["amount"] == expected_amount
    assert req["asset"] == BASE_USDC
    assert req["payTo"] == FLEET_PAY_TO
    # EIP-712 domain parameters for USDC must be advertised.
    assert req["extra"]["name"] == "USD Coin"
    assert req["extra"]["version"] == "2"


def test_parse_challenge_from_body_fallback():
    challenge = load_challenge("token_verdict_402_challenge.json")
    response = httpx.Response(402, json=challenge)
    parsed = parse_payment_required(response)
    assert select_requirement(parsed)["amount"] == "20000"


def test_parse_rejects_garbage():
    response = httpx.Response(402, text="not a challenge")
    with pytest.raises(ValueError):
        parse_payment_required(response)


def test_select_requirement_rejects_missing_network():
    challenge = load_challenge("token_verdict_402_challenge.json")
    challenge["accepts"] = [dict(challenge["accepts"][0], network="eip155:1")]
    with pytest.raises(ValueError):
        select_requirement(challenge)
