from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .universe import normalize_symbol

SHANGHAI = ZoneInfo("Asia/Shanghai")
DECISION_CLOCKS = ("14:35", "14:45", "14:50")
DECISION_SNAPSHOT_SCHEMA_VERSION = "X_DECISION_SNAPSHOT_V0.1"
DECISION_SNAPSHOT_COLUMNS = (
    "trade_date",
    "symbol",
    "decision_ts",
    "price",
    "vwap",
    "ret_10m",
    "ret_20m",
    "ret_30m",
    "volume",
    "volume_unit",
    "turnover",
    "turnover_unit",
    "intraday_position",
    "volatility",
    "atr",
    "industry_id",
    "stock_vs_industry",
    "market_context",
    "tradable",
    "unavailable_reason",
    "source",
    "source_timestamp",
    "feature_available_at",
    "fetched_at",
    "security_master_asof",
    "feature_schema_version",
)
_REQUIRED_TRADABLE_VALUES = (
    "price",
    "vwap",
    "ret_10m",
    "ret_20m",
    "ret_30m",
    "volume",
    "turnover",
    "intraday_position",
    "volatility",
    "atr",
    "stock_vs_industry",
)


class DecisionSnapshotContractError(ValueError):
    pass


def _timestamps(values: pd.Series, *, field: str, nullable: bool = False) -> pd.Series:
    result: list[pd.Timestamp | pd.NaT] = []
    for value in values:
        if pd.isna(value):
            if nullable:
                result.append(pd.NaT)
                continue
            raise DecisionSnapshotContractError(f"{field} is required")
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            raise DecisionSnapshotContractError(
                f"{field} must be timezone-aware; naive timestamps are ambiguous"
            )
        result.append(stamp.tz_convert(SHANGHAI))
    return pd.Series(result, index=values.index, dtype="datetime64[ns, Asia/Shanghai]")


def validate_decision_snapshot_frame(
    rows: pd.DataFrame,
    *,
    universe_symbols: Iterable[str],
) -> pd.DataFrame:
    """Validate one trade day's complete 14:35/14:45/14:50 universe cube.

    ``feature_available_at`` is the maximum availability timestamp across every
    derived input in a row. ``fetched_at`` may be later during historical
    ingestion; it is audit metadata and is never treated as feature time.
    """

    missing = set(DECISION_SNAPSHOT_COLUMNS).difference(rows.columns)
    if missing:
        raise DecisionSnapshotContractError(
            f"decision snapshot missing columns: {sorted(missing)}"
        )
    frame = rows.loc[:, DECISION_SNAPSHOT_COLUMNS].copy()
    frame["symbol"] = frame["symbol"].map(normalize_symbol)
    expected_symbols = {normalize_symbol(symbol) for symbol in universe_symbols}
    if not expected_symbols:
        raise DecisionSnapshotContractError("universe_symbols cannot be empty")
    for field in (
        "decision_ts",
        "source_timestamp",
        "feature_available_at",
        "fetched_at",
        "security_master_asof",
    ):
        frame[field] = _timestamps(frame[field], field=field)

    parsed_dates = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
    if parsed_dates.isna().any():
        raise DecisionSnapshotContractError("trade_date contains invalid values")
    frame["trade_date"] = parsed_dates
    trade_dates: set[date] = set(frame["trade_date"])
    if len(trade_dates) != 1:
        raise DecisionSnapshotContractError(
            "one snapshot batch must contain exactly one trade_date"
        )

    if (frame["feature_schema_version"] != DECISION_SNAPSHOT_SCHEMA_VERSION).any():
        raise DecisionSnapshotContractError(
            "unsupported decision-snapshot schema version"
        )
    clocks = frame["decision_ts"].dt.strftime("%H:%M")
    if not clocks.isin(DECISION_CLOCKS).all():
        invalid = sorted(clocks[~clocks.isin(DECISION_CLOCKS)].unique())
        raise DecisionSnapshotContractError(f"unsupported decision clocks: {invalid}")
    if (
        (frame["decision_ts"].dt.second != 0)
        | (frame["decision_ts"].dt.microsecond != 0)
        | (frame["decision_ts"].dt.nanosecond != 0)
    ).any():
        raise DecisionSnapshotContractError(
            "decision_ts must be an exact decision minute"
        )
    local_dates = frame["decision_ts"].dt.date
    if not (local_dates == frame["trade_date"]).all():
        raise DecisionSnapshotContractError(
            "decision_ts local date must equal trade_date"
        )

    for field in ("source_timestamp", "feature_available_at", "security_master_asof"):
        future = frame[field] > frame["decision_ts"]
        if future.any():
            first = frame.loc[future].iloc[0]
            raise DecisionSnapshotContractError(
                f"future leakage in {field} for {first.symbol} at {first.decision_ts.isoformat()}"
            )
    if (frame["fetched_at"] < frame["source_timestamp"]).any():
        raise DecisionSnapshotContractError(
            "fetched_at cannot precede source_timestamp"
        )

    if frame.duplicated(["symbol", "decision_ts"]).any():
        raise DecisionSnapshotContractError("duplicate symbol/decision_ts rows")
    actual_symbols = set(frame["symbol"])
    if actual_symbols != expected_symbols:
        missing_symbols = sorted(expected_symbols - actual_symbols)
        extra_symbols = sorted(actual_symbols - expected_symbols)
        raise DecisionSnapshotContractError(
            f"universe mismatch: missing={missing_symbols}, extra={extra_symbols}"
        )
    actual_keys = set(zip(frame["symbol"], clocks, strict=True))
    expected_keys = {
        (symbol, clock) for symbol in expected_symbols for clock in DECISION_CLOCKS
    }
    if actual_keys != expected_keys or len(frame) != len(expected_keys):
        missing_keys = sorted(expected_keys - actual_keys)
        extra_keys = sorted(actual_keys - expected_keys)
        raise DecisionSnapshotContractError(
            f"incomplete full-universe snapshot: missing={missing_keys}, extra={extra_keys}"
        )

    if (
        frame["tradable"].isna().any()
        or not frame["tradable"]
        .map(lambda value: isinstance(value, (bool, np.bool_)))
        .all()
    ):
        raise DecisionSnapshotContractError("tradable must contain real booleans")
    tradable = frame["tradable"]
    numeric = frame.loc[tradable, _REQUIRED_TRADABLE_VALUES].apply(
        pd.to_numeric, errors="coerce"
    )
    if (
        numeric.isna().any().any()
        or not np.isfinite(numeric.to_numpy(dtype=float)).all()
    ):
        raise DecisionSnapshotContractError(
            "tradable rows require every numeric feature"
        )
    if frame.loc[tradable, ["industry_id", "market_context"]].isna().any().any():
        raise DecisionSnapshotContractError(
            "tradable rows require industry_id and market_context"
        )
    if (numeric[["price", "vwap"]] <= 0).any().any():
        raise DecisionSnapshotContractError("tradable price and vwap must be positive")
    if (numeric[["volume", "turnover", "volatility", "atr"]] < 0).any().any():
        raise DecisionSnapshotContractError(
            "volume, turnover, volatility, and atr cannot be negative"
        )
    if ((numeric["intraday_position"] < 0) | (numeric["intraday_position"] > 1)).any():
        raise DecisionSnapshotContractError("intraday_position must be between 0 and 1")
    unavailable_without_reason = (~tradable) & (
        frame["unavailable_reason"].isna()
        | (frame["unavailable_reason"].astype("string").str.strip() == "")
    )
    if unavailable_without_reason.any():
        raise DecisionSnapshotContractError(
            "non-tradable rows require unavailable_reason"
        )
    return frame.sort_values(["decision_ts", "symbol"]).reset_index(drop=True)
