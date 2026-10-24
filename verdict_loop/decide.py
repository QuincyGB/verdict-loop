"""Decision policy: turn service verdicts into screening decisions.

Pure functions over the services' published output shapes (see each
service's /.well-known/x402 output schema):

Token Verdict  POST /v1/verdict -> {"verdict": SOLID|CAUTION|DANGER,
    "score": 0-100 RISK (0 = safest), ...}
    Policy: WOULD_BUY only a SOLID verdict whose risk score is at or
    under `max_risk_score`. Everything else is a SKIP — a CAUTION with
    a low numeric score is still a skip: the analyst label outranks the
    number.

RouteVerdict   POST /v1/check   -> {"verdict": TRUSTED|CAUTION|AVOID,
    "score": 0-100 TRUST (100 = fully trusted), ...}
    Policy: ADOPT only a TRUSTED verdict at or over `min_trust_score`.
    Everything else is a PASS.

Malformed payloads raise ValueError rather than guessing a decision —
a screening loop must fail loud, never invent a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_RISK_SCORE = 40.0
DEFAULT_MIN_TRUST_SCORE = 80.0


@dataclass
class Decision:
    action: str  # WOULD_BUY | SKIP  /  ADOPT | PASS
    reason: str
    verdict: str
    score: float


def _require(payload: dict, *fields: str) -> None:
    missing = [f for f in fields if f not in payload]
    if missing:
        raise ValueError(f"verdict payload is missing fields: {missing}")


def decide_token(
    verdict_payload: dict, *, max_risk_score: float = DEFAULT_MAX_RISK_SCORE
) -> Decision:
    """Map a Token Verdict response to a would-buy / skip decision."""
    _require(verdict_payload, "verdict", "score")
    verdict = str(verdict_payload["verdict"])
    score = float(verdict_payload["score"])
    if verdict not in ("SOLID", "CAUTION", "DANGER"):
        raise ValueError(f"unknown token verdict label: {verdict!r}")
    if verdict == "SOLID" and score <= max_risk_score:
        return Decision(
            "WOULD_BUY",
            f"SOLID with risk score {score:g} <= max {max_risk_score:g}",
            verdict, score,
        )
    if verdict == "SOLID":
        return Decision(
            "SKIP",
            f"SOLID but risk score {score:g} > max {max_risk_score:g}",
            verdict, score,
        )
    return Decision(
        "SKIP", f"verdict is {verdict} (risk score {score:g}); only SOLID is bought",
        verdict, score,
    )


def decide_service(
    check_payload: dict, *, min_trust_score: float = DEFAULT_MIN_TRUST_SCORE
) -> Decision:
    """Map a RouteVerdict response to an adopt / pass decision."""
    _require(check_payload, "verdict", "score")
    verdict = str(check_payload["verdict"])
    score = float(check_payload["score"])
    if verdict not in ("TRUSTED", "CAUTION", "AVOID"):
        raise ValueError(f"unknown route verdict label: {verdict!r}")
    if verdict == "TRUSTED" and score >= min_trust_score:
        return Decision(
            "ADOPT",
            f"TRUSTED with trust score {score:g} >= min {min_trust_score:g}",
            verdict, score,
        )
    if verdict == "TRUSTED":
        return Decision(
            "PASS",
            f"TRUSTED but trust score {score:g} < min {min_trust_score:g}",
            verdict, score,
        )
    return Decision(
        "PASS", f"verdict is {verdict} (trust score {score:g}); only TRUSTED is adopted",
        verdict, score,
    )
