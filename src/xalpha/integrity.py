from __future__ import annotations

from datetime import datetime
from typing import Iterable


def assert_no_future_features(decision_ts: datetime, available_at: Iterable[datetime]) -> None:
    """Hard gate: every feature must have been available no later than decision_ts."""
    leaks = [stamp for stamp in available_at if stamp > decision_ts]
    if leaks:
        first = min(leaks)
        raise ValueError(f"future leakage detected: {first.isoformat()} > {decision_ts.isoformat()}")
