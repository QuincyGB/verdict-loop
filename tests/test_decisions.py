"""Verdict -> decision mapping.

The example outputs are the services' own published examples (extracted
from the bazaar extension inside the real captured 402 challenges).
The boundary cases are minimal payloads built to exercise the policy —
they test this repo's mapping code, they are not service responses.
"""

import json
from pathlib import Path

import pytest

from verdict_loop.decide import decide_service, decide_token

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- real published examples ---------------------------------------------------

def test_real_token_verdict_example_is_a_skip():
    # The service's own example: CAUTION, risk 35.0. The label outranks
    # the number — only SOLID is bought.
    example = load("token_verdict_example_output.json")
    decision = decide_token(example)
    assert decision.action == "SKIP"
    assert decision.verdict == "CAUTION"


def test_real_route_verdict_example_is_adopted():
    # The service's own example: TRUSTED, trust 85.0 >= min 80.
    example = load("route_verdict_example_output.json")
    decision = decide_service(example)
    assert decision.action == "ADOPT"
    assert decision.verdict == "TRUSTED"


# --- token policy boundaries -----------------------------------------------------

@pytest.mark.parametrize(
    "verdict, score, expected",
    [
        ("SOLID", 0.0, "WOULD_BUY"),
        ("SOLID", 40.0, "WOULD_BUY"),   # at the cap: bought
        ("SOLID", 40.5, "SKIP"),        # over the cap: skipped
        ("CAUTION", 1.0, "SKIP"),       # label outranks a low score
        ("DANGER", 99.0, "SKIP"),
    ],
)
def test_token_policy(verdict, score, expected):
    decision = decide_token({"verdict": verdict, "score": score})
    assert decision.action == expected


def test_token_custom_risk_cap():
    decision = decide_token({"verdict": "SOLID", "score": 55.0}, max_risk_score=60)
    assert decision.action == "WOULD_BUY"


# --- service policy boundaries ---------------------------------------------------

@pytest.mark.parametrize(
    "verdict, score, expected",
    [
        ("TRUSTED", 100.0, "ADOPT"),
        ("TRUSTED", 80.0, "ADOPT"),     # at the floor: adopted
        ("TRUSTED", 79.9, "PASS"),
        ("CAUTION", 95.0, "PASS"),      # label outranks a high score
        ("AVOID", 0.0, "PASS"),
    ],
)
def test_service_policy(verdict, score, expected):
    decision = decide_service({"verdict": verdict, "score": score})
    assert decision.action == expected


# --- fail loud, never invent -----------------------------------------------------

def test_missing_fields_raise():
    with pytest.raises(ValueError):
        decide_token({"verdict": "SOLID"})
    with pytest.raises(ValueError):
        decide_service({"score": 10})


def test_unknown_label_raises():
    with pytest.raises(ValueError):
        decide_token({"verdict": "MOON", "score": 1})
    with pytest.raises(ValueError):
        decide_service({"verdict": "FINE", "score": 1})
