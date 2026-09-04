from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xalpha.data import AKShareAdapter, AKShareDataError, MarketDataAdapter
from xalpha.security_master import PointInTimeSecurityMaster

SHANGHAI = ZoneInfo("Asia/Shanghai")
FETCHED_AT = datetime(2026, 9, 4, 16, 0, tzinfo=SHANGHAI)


class FakeAKShare:
    def tool_trade_date_hist_sina(self):
        return pd.DataFrame({"trade_date": ["2026-09-03", "2026-09-04"]})

    def stock_info_a_code_name(self):
        return pd.DataFrame(
            {"code": ["600000", "000001"], "name": ["浦发银行", "平安银行"]}
        )

    def stock_zh_a_hist(self, **kwargs):
        assert kwargs["symbol"] == "600000"
        return pd.DataFrame(
            {
                "日期": ["2026-09-03", "2026-09-04"],
                "开盘": [10.0, 10.1],
                "最高": [10.2, 10.3],
                "最低": [9.9, 10.0],
                "收盘": [10.1, 10.2],
                "成交量": [1000, 1200],
                "成交额": [1010000, 1224000],
            }
        )

    def stock_zh_a_hist_min_em(self, **kwargs):
        assert kwargs["period"] == "1"
        return pd.DataFrame(
            {
                "时间": ["2026-09-04 14:49:00", "2026-09-04 14:50:00"],
                "开盘": [10.0, 10.1],
                "最高": [10.2, 10.2],
                "最低": [9.9, 10.0],
                "收盘": [10.1, 10.15],
                "成交量": [100, 120],
                "成交额": [101000, 121800],
                "均价": [10.05, 10.10],
            }
        )


def _adapter(**kwargs):
    return AKShareAdapter(client=FakeAKShare(), clock=lambda: FETCHED_AT, **kwargs)


def test_adapter_is_provider_neutral_and_current_master_is_not_backfilled():
    adapter = _adapter()
    assert isinstance(adapter, MarketDataAdapter)

    calendar = adapter.fetch_trading_calendar()
    assert list(calendar.normalized["trade_date"]) == [
        date(2026, 9, 3),
        date(2026, 9, 4),
    ]

    master = adapter.fetch_current_security_master()
    assert set(master.normalized["symbol"]) == {"000001", "600000"}
    assert (master.normalized["effective_from"] == FETCHED_AT).all()
    assert (master.normalized["available_at"] == FETCHED_AT).all()
    assert master.audit.availability_policy == "current_snapshot_valid_from_fetch_only"
    assert len(PointInTimeSecurityMaster(master.normalized).universe(FETCHED_AT)) == 2


def test_minute_bar_availability_requires_explicit_timestamp_semantics():
    unverified = _adapter().fetch_minute_bars(
        "600000",
        start="2026-09-04 14:49:00",
        end="2026-09-04 14:50:00",
    )
    assert unverified.normalized["available_at"].isna().all()
    assert not unverified.normalized["availability_verified"].any()

    verified = _adapter(minute_timestamp_semantics="bar_end").fetch_minute_bars(
        "600000",
        start="2026-09-04 14:49:00",
        end="2026-09-04 14:50:00",
    )
    assert verified.normalized["available_at"].equals(verified.normalized["timestamp"])
    assert verified.normalized["availability_verified"].all()
    assert set(verified.normalized["volume_unit"]) == {"provider_native_unverified"}
    assert verified.audit.endpoint == "stock_zh_a_hist_min_em"

    start_labeled = _adapter(minute_timestamp_semantics="bar_start").fetch_minute_bars(
        "600000",
        start="2026-09-04 14:49:00",
        end="2026-09-04 14:50:00",
    )
    assert start_labeled.normalized.iloc[0].available_at == pd.Timestamp(
        "2026-09-04 14:50", tz=SHANGHAI
    )


def test_daily_bars_use_conservative_next_midnight_availability():
    batch = _adapter().fetch_daily_bars(
        "600000", start_date="20260903", end_date="20260904"
    )
    same_day = batch.normalized.loc[
        batch.normalized["trade_date"] == pd.Timestamp("2026-09-04")
    ].iloc[0]
    assert same_day.available_at == pd.Timestamp("2026-09-05", tz=SHANGHAI)
    assert batch.audit.availability_policy == "daily_bar_conservative_next_midnight"


def test_provider_failures_are_normalized_at_adapter_boundary():
    class FailingAKShare(FakeAKShare):
        def stock_zh_a_hist(self, **kwargs):
            raise ConnectionError("provider unavailable")

    adapter = AKShareAdapter(client=FailingAKShare(), clock=lambda: FETCHED_AT)
    with pytest.raises(
        AKShareDataError, match="stock_zh_a_hist failed with ConnectionError"
    ):
        adapter.fetch_daily_bars("600000", start_date="20260903", end_date="20260904")
