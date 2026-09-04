from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


PathOutcome = Literal["UP_FIRST", "DOWN_FIRST", "AMBIGUOUS", "NEITHER"]


@dataclass(frozen=True)
class DecisionSnapshot:
    trade_date: str
    symbol: str
    decision_ts: datetime
    price: float
    source: str
    source_timestamp: datetime
    feature_schema_version: str = "X_FEATURE_V0.1"

    def validate(self) -> None:
        if self.price <= 0:
            raise ValueError("decision price must be positive")
        if self.source_timestamp > self.decision_ts:
            raise ValueError("future leakage: source_timestamp is later than decision_ts")


@dataclass(frozen=True)
class NextMorningOutcome:
    next_open_return: float | None
    next_0935_return: float
    next_0945_return: float
    next_1000_return: float
    open30_mfe: float
    open30_mae: float
    peak_to_trough_drawdown: float
    hit_plus_0_5: bool
    hit_plus_1_0: bool
    hit_plus_1_5: bool
    hit_minus_0_5: bool
    hit_minus_1_0: bool
    first_touch_plus_1: str | None
    first_touch_minus_1: str | None
    plus1_before_minus1: PathOutcome
    time_to_mfe: str
    time_to_mae: str
