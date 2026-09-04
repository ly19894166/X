from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xalpha.data.base import DataAudit, DataBatch
from xalpha.data.qualification import FreshnessPolicy, FreshnessStatus
from xalpha.data.router import ProviderRouteError, route_data_batch

SHANGHAI = ZoneInfo("Asia/Shanghai")
BASE = datetime(2026, 9, 4, 14, 50, tzinfo=SHANGHAI)


def make_batch(source: str, *, staleness_seconds: int) -> DataBatch:
    audit = DataAudit(
        dataset="snapshot",
        source=source,
        endpoint="fixture",
        params={},
        source_timestamp=BASE - timedelta(seconds=staleness_seconds),
        fetched_at=BASE,
        schema_version="TEST",
        availability_policy="verified",
    )
    return DataBatch(
        raw=pd.DataFrame({"x": [1]}),
        normalized=pd.DataFrame({"x": [1]}),
        audit=audit,
    )


def test_router_falls_back_from_stale_primary_to_fresh_backup():
    result = route_data_batch(
        primary=lambda: make_batch("primary", staleness_seconds=400),
        backups=[lambda: make_batch("backup", staleness_seconds=90)],
        policy=FreshnessPolicy(),
    )
    assert result.selected_role == "BACKUP"
    assert result.batch.audit.source == "backup"
    assert result.freshness_status is FreshnessStatus.ACCEPTABLE
    assert len(result.attempts) == 2


def test_router_uses_cache_only_if_cache_is_still_eligible():
    result = route_data_batch(
        primary=lambda: (_ for _ in ()).throw(ConnectionError("down")),
        cache_loader=lambda: make_batch("cache", staleness_seconds=120),
    )
    assert result.selected_role == "CACHE"
    assert result.batch.audit.source == "cache"


def test_router_fails_closed_when_every_source_is_unusable():
    with pytest.raises(ProviderRouteError) as excinfo:
        route_data_batch(
            primary=lambda: make_batch("primary", staleness_seconds=600),
            backups=[lambda: make_batch("backup", staleness_seconds=301)],
        )
    assert len(excinfo.value.attempts) == 2
