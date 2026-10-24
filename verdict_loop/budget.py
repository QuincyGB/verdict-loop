"""Daily spend cap for live mode.

The cap is the loop's hard safety rail: a JSON ledger on disk records
what was actually settled today (UTC). `authorize()` is checked BEFORE
any payment is signed and raises `SpendCapExceeded` when the payment
would push the day over the cap — so a misconfigured watchlist or a
price change upstream can never silently overspend. A new UTC day
starts a fresh ledger.

Amounts are USDC base units (6 decimals): the default $0.10 cap is
100_000 units.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .x402 import SpendCapExceeded, format_usd

DEFAULT_DAILY_CAP_UNITS = 100_000  # $0.10


class DailySpendCap:
    def __init__(
        self,
        cap_units: int = DEFAULT_DAILY_CAP_UNITS,
        state_path: str | Path | None = None,
        *,
        now: datetime | None = None,
    ):
        if cap_units <= 0:
            raise ValueError("daily cap must be positive")
        self.cap_units = cap_units
        self.state_path = Path(state_path) if state_path else None
        self._now = now  # injectable clock for tests
        self._date, self._spent_units, self._calls = self._load()

    # -- clock / persistence -------------------------------------------------

    def _today(self) -> str:
        now = self._now or datetime.now(timezone.utc)
        return now.date().isoformat()

    def _load(self) -> tuple[str, int, list]:
        today = self._today()
        if self.state_path and self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = None
            if isinstance(data, dict) and data.get("date") == today:
                return today, int(data.get("spent_units", 0)), list(data.get("calls", []))
        # Missing, corrupt, or a previous day's ledger -> fresh day.
        return today, 0, []

    def _save(self) -> None:
        if not self.state_path:
            return
        payload = {
            "date": self._date,
            "cap_units": self.cap_units,
            "spent_units": self._spent_units,
            "calls": self._calls,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # -- the rail --------------------------------------------------------------

    @property
    def spent_units(self) -> int:
        return self._spent_units

    @property
    def remaining_units(self) -> int:
        return max(0, self.cap_units - self._spent_units)

    def authorize(self, units: int) -> None:
        """Raise SpendCapExceeded if paying `units` would break the cap."""
        if units < 0:
            raise ValueError("payment amount cannot be negative")
        if self._spent_units + units > self.cap_units:
            raise SpendCapExceeded(
                f"daily spend cap: paying {format_usd(units)} would bring today to "
                f"{format_usd(self._spent_units + units)}, over the "
                f"{format_usd(self.cap_units)} cap "
                f"(already spent {format_usd(self._spent_units)})"
            )

    def record(self, units: int, *, label: str = "") -> None:
        """Record a settled payment. Call only after the service answered."""
        self.authorize(units)  # recording a settled payment may never break the cap either
        self._spent_units += units
        self._calls.append({"units": units, "label": label})
        self._save()
