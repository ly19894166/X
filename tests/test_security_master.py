from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xalpha.security_master import (
    SECURITY_MASTER_SCHEMA_VERSION,
    PointInTimeSecurityMaster,
    SecurityMasterContractError,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _stamp(text: str):
    return pd.Timestamp(text, tz=SHANGHAI)


def _row(
    symbol: str,
    name: str,
    effective_from: str,
    effective_to: str | None,
    available_at: str,
):
    available = _stamp(available_at)
    return {
        "symbol": symbol,
        "name": name,
        "exchange": "SSE" if symbol.startswith("6") else "SZSE",
        "board": "SSE_MAIN" if symbol.startswith("6") else "SZSE_MAIN",
        "status": "LISTED",
        "is_st": "ST" in name,
        "is_suspended": False,
        "listed_on": _stamp("2020-01-01 00:00"),
        "delisted_on": pd.NaT,
        "effective_from": _stamp(effective_from),
        "effective_to": _stamp(effective_to) if effective_to else pd.NaT,
        "available_at": available,
        "source": "fixture",
        "source_timestamp": available,
        "fetched_at": max(available, _stamp("2026-07-01 00:00")),
        "schema_version": SECURITY_MASTER_SCHEMA_VERSION,
    }


def test_point_in_time_lookup_uses_effective_and_knowledge_time():
    records = pd.DataFrame(
        [
            _row("600000", "旧名称", "2026-01-01", "2026-06-01", "2026-01-01"),
            _row("600000", "新名称", "2026-06-01", None, "2026-06-01"),
            _row("000001", "晚到记录", "2026-01-01", None, "2026-09-05"),
        ]
    )
    master = PointInTimeSecurityMaster(records)
    may = master.as_of(datetime(2026, 5, 15, 14, 50, tzinfo=SHANGHAI))
    assert may.set_index("symbol").loc["600000", "name"] == "旧名称"

    september = master.universe(datetime(2026, 9, 4, 14, 50, tzinfo=SHANGHAI))
    assert september.set_index("symbol").loc["600000", "name"] == "新名称"
    assert "000001" not in set(september["symbol"])


def test_security_master_rejects_overlapping_intervals():
    records = pd.DataFrame(
        [
            _row("600000", "版本一", "2026-01-01", None, "2026-01-01"),
            _row("600000", "版本二", "2026-06-01", None, "2026-06-01"),
        ]
    )
    with pytest.raises(SecurityMasterContractError, match="overlapping"):
        PointInTimeSecurityMaster(records)
