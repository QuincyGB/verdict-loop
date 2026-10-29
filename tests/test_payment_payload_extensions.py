"""Regression: the payment payload MUST echo the challenge's
`extensions` (the Bazaar discovery declaration).

Facilitator catalogues (CDP Bazaar, PayAI) index a resource from the
payment payload's bazaar extension, not from the seller's 402. Before
2026-10-29 this client dropped the field: payments settled but were
never catalogued — the root cause of the fleet's settled-but-unindexed
routes (drought-fix report, 2026-10-29).
"""

import json
from pathlib import Path

from verdict_loop.x402 import build_payment_payload

FIXTURES = Path(__file__).parent / "fixtures"


def _payload(challenge):
    requirement = challenge["accepts"][0]
    authorization = {
        "from": "0x0000000000000000000000000000000000000001",
        "to": requirement["payTo"],
        "value": requirement["amount"],
        "validAfter": "0",
        "validBefore": "9999999999",
        "nonce": "0x" + "00" * 32,
    }
    return build_payment_payload(challenge, requirement, authorization, "0xdeadbeef")


def test_payload_echoes_bazaar_extension_from_real_challenge():
    challenge = json.loads(
        (FIXTURES / "token_verdict_402_challenge.json").read_text(encoding="utf-8")
    )
    assert "bazaar" in challenge["extensions"]  # fixture sanity
    payload = _payload(challenge)
    assert payload["extensions"] == challenge["extensions"]
    assert payload["extensions"]["bazaar"]["info"]["input"]["method"] == "POST"


def test_payload_without_extensions_stays_clean():
    challenge = {
        "x402Version": 2,
        "resource": {"url": "https://example.com/v1/x"},
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "amount": "1000",
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "payTo": "0x097f9685D1e0752bF8B02d61E5Ce9be7eA0FBA7F",
            }
        ],
    }
    payload = _payload(challenge)
    assert "extensions" not in payload
