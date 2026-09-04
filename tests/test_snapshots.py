from datetime import timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xalpha.snapshots import (
    DECISION_CLOCKS,
    DECISION_SNAPSHOT_SCHEMA_VERSION,
    DecisionSnapshotContractError,
    validate_decision_snapshot_frame,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
UNIVERSE = ["600000", "000001"]


def _frame() -> pd.DataFrame:
    rows = []
    for clock in DECISION_CLOCKS:
        decision = pd.Timestamp(f"2026-09-04 {clock}", tz=SHANGHAI)
        for symbol in UNIVERSE:
            rows.append(
                {
                    "trade_date": "2026-09-04",
                    "symbol": symbol,
                    "decision_ts": decision,
                    "price": 10.0,
                    "vwap": 9.9,
                    "ret_10m": 0.001,
                    "ret_20m": 0.002,
                    "ret_30m": 0.003,
                    "volume": 1000.0,
                    "volume_unit": "provider_native_unverified",
                    "turnover": 10000.0,
                    "turnover_unit": "CNY_unverified",
                    "intraday_position": 0.7,
                    "volatility": 0.02,
                    "atr": 0.3,
                    "industry_id": "BANK",
                    "stock_vs_industry": 0.001,
                    "market_context": '{"market_ret":0.001}',
                    "tradable": True,
                    "unavailable_reason": None,
                    "source": "akshare",
                    "source_timestamp": decision,
                    "feature_available_at": decision,
                    "fetched_at": decision + timedelta(days=1),
                    "security_master_asof": decision - timedelta(minutes=1),
                    "feature_schema_version": DECISION_SNAPSHOT_SCHEMA_VERSION,
                }
            )
    return pd.DataFrame(rows)


def test_full_universe_three_clock_contract_accepts_later_audit_fetch():
    validated = validate_decision_snapshot_frame(_frame(), universe_symbols=UNIVERSE)
    assert len(validated) == len(UNIVERSE) * len(DECISION_CLOCKS)
    assert set(validated["decision_ts"].dt.strftime("%H:%M")) == set(DECISION_CLOCKS)


@pytest.mark.parametrize(
    "field", ["source_timestamp", "feature_available_at", "security_master_asof"]
)
def test_snapshot_rejects_every_future_information_channel(field):
    frame = _frame()
    frame.loc[0, field] = frame.loc[0, "decision_ts"] + timedelta(minutes=1)
    with pytest.raises(
        DecisionSnapshotContractError, match=f"future leakage in {field}"
    ):
        validate_decision_snapshot_frame(frame, universe_symbols=UNIVERSE)


def test_snapshot_rejects_incomplete_universe_cube():
    frame = _frame().iloc[:-1]
    with pytest.raises(DecisionSnapshotContractError, match="incomplete full-universe"):
        validate_decision_snapshot_frame(frame, universe_symbols=UNIVERSE)


def test_non_tradable_symbol_remains_in_universe_with_reason():
    frame = _frame()
    mask = frame["symbol"] == "000001"
    frame.loc[mask, "tradable"] = False
    frame.loc[mask, "unavailable_reason"] = "SUSPENDED"
    frame.loc[mask, "price"] = pd.NA
    validated = validate_decision_snapshot_frame(frame, universe_symbols=UNIVERSE)
    assert len(validated[validated["symbol"] == "000001"]) == 3


def test_snapshot_rejects_naive_decision_timestamp():
    frame = _frame()
    frame["decision_ts"] = frame["decision_ts"].astype(object)
    frame.at[0, "decision_ts"] = pd.Timestamp("2026-09-04 14:35")
    with pytest.raises(DecisionSnapshotContractError, match="timezone-aware"):
        validate_decision_snapshot_frame(frame, universe_symbols=UNIVERSE)


def test_snapshot_requires_exact_minute_and_numeric_features():
    frame = _frame()
    frame.loc[0, "decision_ts"] = frame.loc[0, "decision_ts"] + timedelta(seconds=1)
    with pytest.raises(DecisionSnapshotContractError, match="exact decision minute"):
        validate_decision_snapshot_frame(frame, universe_symbols=UNIVERSE)

    frame = _frame()
    frame["ret_10m"] = frame["ret_10m"].astype(object)
    frame.at[0, "ret_10m"] = "not-a-number"
    with pytest.raises(DecisionSnapshotContractError, match="numeric feature"):
        validate_decision_snapshot_frame(frame, universe_symbols=UNIVERSE)
