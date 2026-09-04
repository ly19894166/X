from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Iterable

import pandas as pd


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    ACCEPTABLE = "ACCEPTABLE"
    STALE_WARNING = "STALE_WARNING"
    STALE_REJECT = "STALE_REJECT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FreshnessPolicy:
    """Engineering thresholds for X's minute-level research workflow.

    These are not market facts. They are configurable acceptance thresholds for
    a human-in-the-loop, non-HFT strategy. Historical replay must use the same
    policy as live ingestion.
    """

    fresh_max_seconds: float = 60.0
    acceptable_max_seconds: float = 180.0
    warning_max_seconds: float = 300.0
    allow_warning_for_decision: bool = False

    def __post_init__(self) -> None:
        values = (
            self.fresh_max_seconds,
            self.acceptable_max_seconds,
            self.warning_max_seconds,
        )
        if any(value < 0 for value in values):
            raise ValueError("freshness thresholds cannot be negative")
        if not (values[0] <= values[1] <= values[2]):
            raise ValueError("freshness thresholds must be monotonic")

    def classify_seconds(self, staleness_seconds: float | None) -> FreshnessStatus:
        if staleness_seconds is None:
            return FreshnessStatus.UNKNOWN
        value = float(staleness_seconds)
        if value < 0:
            raise ValueError("staleness cannot be negative")
        if value <= self.fresh_max_seconds:
            return FreshnessStatus.FRESH
        if value <= self.acceptable_max_seconds:
            return FreshnessStatus.ACCEPTABLE
        if value <= self.warning_max_seconds:
            return FreshnessStatus.STALE_WARNING
        return FreshnessStatus.STALE_REJECT

    def decision_eligible(self, status: FreshnessStatus) -> bool:
        if status in {FreshnessStatus.FRESH, FreshnessStatus.ACCEPTABLE}:
            return True
        return status is FreshnessStatus.STALE_WARNING and self.allow_warning_for_decision


@dataclass(frozen=True)
class ProviderObservation:
    provider: str
    dataset: str
    requested_at: datetime
    received_at: datetime
    success: bool
    symbol: str = ""
    event_time: datetime | None = None
    provider_time: datetime | None = None
    timeout: bool = False
    parse_error: bool = False
    row_count: int = 0
    error_type: str = ""
    error_message: str = ""

    def validate(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider is required")
        if not self.dataset.strip():
            raise ValueError("dataset is required")
        if self.requested_at.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("requested_at and received_at must be timezone-aware")
        if self.received_at < self.requested_at:
            raise ValueError("received_at cannot be earlier than requested_at")
        for stamp in (self.event_time, self.provider_time):
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError("event/provider timestamps must be timezone-aware")
        if self.row_count < 0:
            raise ValueError("row_count cannot be negative")
        if self.success and (self.timeout or self.parse_error):
            raise ValueError("successful observation cannot be timeout/parse_error")

    @property
    def request_latency_seconds(self) -> float:
        return (self.received_at - self.requested_at).total_seconds()

    @property
    def staleness_seconds(self) -> float | None:
        anchor = self.event_time or self.provider_time
        if anchor is None:
            return None
        value = (self.received_at - anchor).total_seconds()
        return max(0.0, value)

    def freshness(self, policy: FreshnessPolicy) -> FreshnessStatus:
        return policy.classify_seconds(self.staleness_seconds)

    def as_record(self, policy: FreshnessPolicy) -> dict[str, object]:
        self.validate()
        status = self.freshness(policy)
        return {
            "provider": self.provider,
            "dataset": self.dataset,
            "symbol": self.symbol,
            "requested_at": self.requested_at,
            "event_time": self.event_time,
            "provider_time": self.provider_time,
            "received_at": self.received_at,
            "request_latency_seconds": self.request_latency_seconds,
            "staleness_seconds": self.staleness_seconds,
            "freshness_status": status.value,
            "decision_eligible": policy.decision_eligible(status),
            "success": self.success,
            "timeout": self.timeout,
            "parse_error": self.parse_error,
            "row_count": self.row_count,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


def observations_frame(
    observations: Iterable[ProviderObservation],
    *,
    policy: FreshnessPolicy | None = None,
) -> pd.DataFrame:
    active = policy or FreshnessPolicy()
    rows = [item.as_record(active) for item in observations]
    return pd.DataFrame(rows)


def summarize_observations(
    observations: Iterable[ProviderObservation],
    *,
    policy: FreshnessPolicy | None = None,
) -> pd.DataFrame:
    frame = observations_frame(observations, policy=policy)
    columns = [
        "provider",
        "dataset",
        "samples",
        "success_rate",
        "timeout_rate",
        "parse_error_rate",
        "median_request_latency_seconds",
        "p95_request_latency_seconds",
        "median_staleness_seconds",
        "p95_staleness_seconds",
        "decision_eligible_rate",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    results: list[dict[str, object]] = []
    for (provider, dataset), group in frame.groupby(["provider", "dataset"], sort=True):
        staleness = pd.to_numeric(group["staleness_seconds"], errors="coerce").dropna()
        latency = pd.to_numeric(group["request_latency_seconds"], errors="coerce")
        results.append(
            {
                "provider": provider,
                "dataset": dataset,
                "samples": int(len(group)),
                "success_rate": float(group["success"].mean()),
                "timeout_rate": float(group["timeout"].mean()),
                "parse_error_rate": float(group["parse_error"].mean()),
                "median_request_latency_seconds": float(latency.median()),
                "p95_request_latency_seconds": float(latency.quantile(0.95)),
                "median_staleness_seconds": (
                    float(staleness.median()) if not staleness.empty else float("nan")
                ),
                "p95_staleness_seconds": (
                    float(staleness.quantile(0.95)) if not staleness.empty else float("nan")
                ),
                "decision_eligible_rate": float(group["decision_eligible"].mean()),
            }
        )
    return pd.DataFrame(results, columns=columns)
