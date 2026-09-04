from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from xalpha.security_master import PointInTimeSecurityMaster, SECURITY_MASTER_SCHEMA_VERSION
from xalpha.snapshot_builder import build_full_universe_snapshot_cube, decision_timestamp

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _master() -> PointInTimeSecurityMaster:
    known = datetime(2026, 9, 7, 9, 0, tzinfo=SHANGHAI)
    rows = []
    for symbol, name, is_st in [("600001", "A", False), ("000001", "ST B", True)]:
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "exchange": "SSE" if symbol.startswith("6") else "SZSE",
                "board": "MAIN",
                "status": "LISTED",
                "is_st": is_st,
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
        )
    return PointInTimeSecurityMaster(pd.DataFrame(rows))


def _features(day: date, clock: str) -> pd.DataFrame:
    decision = decision_timestamp(day, clock)
    available = decision - timedelta(seconds=30)
    rows = []
    for symbol, price in [("600001", 10.0), ("000001", 8.0)]:
        rows.append(
            {
                "symbol": symbol,
                "price": price,
                "vwap": price - 0.05,
                "ret_10m": 0.01,
                "ret_20m": 0.015,
                "ret_30m": 0.02,
                "volume": 1000.0,
                "volume_unit": "hand",
                "turnover": 100000.0,
                "turnover_unit": "CNY",
                "intraday_position": 0.7,
                "volatility": 0.02,
                "atr": 0.3,
                "industry_id": "I1",
                "stock_vs_industry": 0.01,
                "market_context": "NEUTRAL",
                "source": "fixture_market",
                "source_timestamp": available,
                "feature_available_at": available,
                "fetched_at": decision - timedelta(seconds=10),
            }
        )
    return pd.DataFrame(rows)


def test_build_full_universe_cube_keeps_st_in_denominator():
    day = date(2026, 9, 7)
    cube = build_full_universe_snapshot_cube(
        master=_master(),
        trade_date=day,
        feature_frames={clock: _features(day, clock) for clock in ("14:35", "14:45", "14:50")},
    )
    assert len(cube) == 6
    st_rows = cube[cube["symbol"] == "000001"]
    assert len(st_rows) == 3
    assert not st_rows["tradable"].any()
    assert set(st_rows["unavailable_reason"]) == {"ST"}
    assert cube[cube["symbol"] == "600001"]["tradable"].all()
