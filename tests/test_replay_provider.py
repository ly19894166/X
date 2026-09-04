from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from xalpha.data.base import DataAudit, DataBatch
from xalpha.data.replay import ReplayFixtureMissing, ReplayProvider

SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_batch() -> DataBatch:
    stamp = datetime(2026, 9, 4, 14, 49, tzinfo=SHANGHAI)
    audit = DataAudit(
        dataset="minute_bars",
        source="fixture",
        endpoint="fixture",
        params={},
        source_timestamp=stamp,
        fetched_at=stamp,
        schema_version="TEST",
        availability_policy="fixture",
    )
    return DataBatch(
        raw=pd.DataFrame({"close": [10.0]}),
        normalized=pd.DataFrame({"close": [10.0]}),
        audit=audit,
    )


def test_replay_returns_deep_copies():
    provider = ReplayProvider({"a": make_batch()})
    first = provider.get("a")
    second = provider.get("a")
    first.normalized.loc[0, "close"] = 99.0
    assert second.normalized.loc[0, "close"] == 10.0


def test_replay_missing_fixture_is_explicit():
    provider = ReplayProvider({})
    try:
        provider.get("missing")
    except ReplayFixtureMissing:
        pass
    else:
        raise AssertionError("missing replay fixture must fail explicitly")
