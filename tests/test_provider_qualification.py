from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from xalpha.data.qualification import (
    FreshnessPolicy,
    FreshnessStatus,
    ProviderObservation,
    summarize_observations,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_freshness_policy_boundaries():
    policy = FreshnessPolicy()
    assert policy.classify_seconds(60) is FreshnessStatus.FRESH
    assert policy.classify_seconds(61) is FreshnessStatus.ACCEPTABLE
    assert policy.classify_seconds(180) is FreshnessStatus.ACCEPTABLE
    assert policy.classify_seconds(181) is FreshnessStatus.STALE_WARNING
    assert policy.classify_seconds(300) is FreshnessStatus.STALE_WARNING
    assert policy.classify_seconds(301) is FreshnessStatus.STALE_REJECT
    assert policy.decision_eligible(FreshnessStatus.ACCEPTABLE)
    assert not policy.decision_eligible(FreshnessStatus.STALE_WARNING)


def test_provider_observation_and_summary():
    base = datetime(2026, 9, 4, 14, 50, tzinfo=SHANGHAI)
    observations = [
        ProviderObservation(
            provider="p1",
            dataset="snapshot",
            requested_at=base,
            received_at=base + timedelta(seconds=2),
            event_time=base - timedelta(seconds=30),
            success=True,
            row_count=5000,
        ),
        ProviderObservation(
            provider="p1",
            dataset="snapshot",
            requested_at=base + timedelta(minutes=1),
            received_at=base + timedelta(minutes=1, seconds=3),
            event_time=base - timedelta(seconds=20),
            success=True,
            row_count=5000,
        ),
    ]
    summary = summarize_observations(observations)
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["samples"] == 2
    assert row["success_rate"] == 1.0
    assert row["decision_eligible_rate"] == 1.0
