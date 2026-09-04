from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xalpha.data import (
    AuditedLocalCache,
    CacheCollisionError,
    CacheIntegrityError,
    DataAudit,
    DataBatch,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _batch(value: float = 10.0) -> DataBatch:
    audit = DataAudit(
        dataset="minute_bars",
        source="akshare",
        endpoint="stock_zh_a_hist_min_em",
        params={"symbol": "600000", "period": "1"},
        source_timestamp=datetime(2026, 9, 4, 14, 50, tzinfo=SHANGHAI),
        fetched_at=datetime(2026, 9, 4, 16, 0, tzinfo=SHANGHAI),
        schema_version="X_MINUTE_BAR_V0.1",
        units={"volume": "provider_native_unverified"},
        availability_policy="minute_timestamp_bar_end",
    )
    raw = pd.DataFrame({"代码": ["600000"], "收盘": [value]})
    normalized = pd.DataFrame(
        {
            "symbol": ["600000"],
            "close": [value],
            "timestamp": [pd.Timestamp("2026-09-04 14:50", tz=SHANGHAI)],
            "optional_flag": pd.Series([pd.NA], dtype="boolean"),
        }
    )
    return DataBatch(raw=raw, normalized=normalized, audit=audit)


def test_cache_round_trip_is_idempotent_and_audited(tmp_path):
    cache = AuditedLocalCache(tmp_path)
    first = cache.store(_batch(), partition="trade_date=2026-09-04")
    second = cache.store(_batch(), partition="trade_date=2026-09-04")
    assert first == second
    assert len(first.raw_sha256) == 64
    assert len(first.normalized_sha256) == 64

    loaded = cache.load(_batch().audit, partition="trade_date=2026-09-04")
    assert loaded.raw.loc[0, "代码"] == "600000"
    assert loaded.normalized.loc[0, "close"] == 10.0
    assert loaded.normalized.loc[0, "timestamp"] == pd.Timestamp(
        "2026-09-04 14:50", tz=SHANGHAI
    )
    assert pd.isna(loaded.normalized.loc[0, "optional_flag"])
    assert loaded.audit.availability_policy == "minute_timestamp_bar_end"

    restarted = AuditedLocalCache(tmp_path).load_partition(
        source="akshare",
        dataset="minute_bars",
        partition="trade_date=2026-09-04",
    )
    assert restarted.audit == loaded.audit


def test_cache_refuses_overwrite_and_detects_corruption(tmp_path):
    cache = AuditedLocalCache(tmp_path)
    entry = cache.store(_batch(), partition="trade_date=2026-09-04")
    with pytest.raises(CacheCollisionError, match="immutable"):
        cache.store(_batch(11.0), partition="trade_date=2026-09-04")

    entry.raw_path.write_text("corrupted\n", encoding="utf-8")
    with pytest.raises(CacheIntegrityError, match="digest mismatch"):
        cache.verify(_batch().audit, partition="trade_date=2026-09-04")


def test_cache_rejects_path_traversal(tmp_path):
    cache = AuditedLocalCache(tmp_path)
    with pytest.raises(ValueError, match="unsafe cache partition"):
        cache.store(_batch(), partition="../outside")
    with pytest.raises(ValueError, match="unsafe cache partition"):
        cache.store(_batch(), partition="..")
