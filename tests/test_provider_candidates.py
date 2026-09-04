from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from xalpha.data.candidates import EastMoneySnapshotCandidate, SinaMinuteCandidate

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 4, 14, 50, tzinfo=SHANGHAI)


class FakeClient:
    def stock_zh_a_spot_em(self):
        return pd.DataFrame(
            {
                "代码": ["600000", "000001"],
                "名称": ["浦发银行", "平安银行"],
                "最新价": [10.0, 11.0],
                "今开": [9.9, 10.9],
                "最高": [10.1, 11.1],
                "最低": [9.8, 10.8],
                "昨收": [9.95, 10.95],
                "成交量": [1000, 2000],
                "成交额": [100000.0, 220000.0],
                "涨跌幅": [0.5, 0.46],
                "换手率": [1.2, 1.5],
            }
        )

    def stock_zh_a_minute(self, **params):
        assert params["symbol"] == "sh600000"
        return pd.DataFrame(
            {
                "day": ["2026-09-04 14:49:00", "2026-09-04 14:50:00"],
                "open": [10.0, 10.02],
                "high": [10.03, 10.04],
                "low": [9.99, 10.01],
                "close": [10.02, 10.03],
                "volume": [100, 120],
            }
        )


def test_eastmoney_snapshot_stays_unverified_until_qualified():
    batch = EastMoneySnapshotCandidate(client=FakeClient(), clock=lambda: NOW).fetch_full_market_snapshot()
    assert len(batch.normalized) == 2
    assert batch.audit.source_timestamp is None
    assert batch.audit.availability_policy == "provider_event_time_unverified"
    assert not batch.normalized["availability_verified"].any()


def test_sina_minute_preserves_provider_time_without_claiming_availability():
    batch = SinaMinuteCandidate(client=FakeClient(), clock=lambda: NOW).fetch_minute_bars("600000")
    assert len(batch.normalized) == 2
    assert batch.audit.source_timestamp is None
    assert batch.normalized["provider_timestamp"].dt.tz is not None
    assert batch.normalized["available_at"].isna().all()
    assert not batch.normalized["availability_verified"].any()
