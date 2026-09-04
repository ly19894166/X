from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from xalpha.security_master import PointInTimeSecurityMaster, SECURITY_MASTER_SCHEMA_VERSION
from xalpha.settlement import build_training_table, settle_snapshot_cube
from xalpha.snapshot_builder import build_full_universe_snapshot_cube, decision_timestamp

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _master() -> PointInTimeSecurityMaster:
    known = datetime(2026, 9, 7, 9, 0, tzinfo=SHANGHAI)
    return PointInTimeSecurityMaster(
        pd.DataFrame(
            [
                {
                    "symbol": "600001",
                    "name": "A",
                    "exchange": "SSE",
                    "board": "MAIN",
                    "status": "LISTED",
                    "is_st": False,
                    "is_suspended": False,
                    "listed_on": datetime(2020, 1, 1, tzinfo=SHANGHAI),
                    "delisted_on": pd.NaT,
                    "effective_from": datetime(2026, 9, 7, 0, 0, tzinfo=SHANGHAI),
                    "effective_to": pd.NaT,
                    "available_at": known,
                    "source": "fixture_master",
                    "source_timestamp": known,
                    "fetched_at": known,
                    "schema_version": SECURITY_MASTER_SCHEMA_VERSION,
                }
            ]
        )
    )


def _features(day: date, clock: str, price: float) -> pd.DataFrame:
    decision = decision_timestamp(day, clock)
    available = decision - timedelta(seconds=20)
    return pd.DataFrame(
        [
            {
                "symbol": "600001",
                "price": price,
                "vwap": price - 0.02,
                "ret_10m": 0.01,
                "ret_20m": 0.01,
                "ret_30m": 0.02,
                "volume": 1000.0,
                "volume_unit": "hand",
                "turnover": 100000.0,
                "turnover_unit": "CNY",
                "intraday_position": 0.8,
                "volatility": 0.02,
                "atr": 0.3,
                "industry_id": "I1",
                "stock_vs_industry": 0.01,
                "market_context": "NEUTRAL",
                "source": "fixture_market",
                "source_timestamp": available,
                "feature_available_at": available,
                "fetched_at": decision - timedelta(seconds=5),
            }
        ]
    )


def _morning(next_day: date) -> pd.DataFrame:
    timestamps = pd.date_range(
        f"{next_day.isoformat()} 09:30",
        f"{next_day.isoformat()} 10:00",
        freq="1min",
        tz=SHANGHAI,
    )
    close = [10.2 + index * 0.01 for index in range(len(timestamps))]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close,
            "high": [value + 0.03 for value in close],
            "low": [value - 0.03 for value in close],
            "close": close,
        }
    )


def test_settlement_keeps_all_three_decision_samples_and_builds_training_table():
    day = date(2026, 9, 7)
    next_day = date(2026, 9, 8)
    cube = build_full_universe_snapshot_cube(
        master=_master(),
        trade_date=day,
        feature_frames={
            "14:35": _features(day, "14:35", 10.0),
            "14:45": _features(day, "14:45", 10.1),
            "14:50": _features(day, "14:50", 10.15),
        },
    )
    calls = []

    def loader(symbol: str, trade_date: date) -> pd.DataFrame:
        calls.append((symbol, trade_date))
        return _morning(trade_date)

    settled = settle_snapshot_cube(cube, next_trade_date=next_day, minute_loader=loader)
    assert len(settled) == 3
    assert set(settled["settlement_status"]) == {"SETTLED"}
    assert len(calls) == 1
    assert settled["next_0935_return"].notna().all()

    training = build_training_table(cube, settled)
    assert len(training) == 3
    assert training["settlement_status"].eq("SETTLED").all()
