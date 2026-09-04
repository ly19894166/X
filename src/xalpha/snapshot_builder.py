from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from .security_master import PointInTimeSecurityMaster
from .snapshots import (
    DECISION_CLOCKS,
    DECISION_SNAPSHOT_COLUMNS,
    DECISION_SNAPSHOT_SCHEMA_VERSION,
    validate_decision_snapshot_frame,
)
from .universe import normalize_symbol

SHANGHAI = ZoneInfo("Asia/Shanghai")

FEATURE_COLUMNS = (
    "symbol",
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
    "source",
    "source_timestamp",
    "feature_available_at",
    "fetched_at",
)
_REQUIRED_TRADABLE_FEATURES = tuple(
    name
    for name in FEATURE_COLUMNS
    if name not in {"symbol", "source", "source_timestamp", "feature_available_at", "fetched_at"}
)


class SnapshotBuildError(ValueError):
    pass


def decision_timestamp(trade_date: date, clock_text: str) -> pd.Timestamp:
    if clock_text not in DECISION_CLOCKS:
        raise SnapshotBuildError(f"unsupported decision clock: {clock_text}")
    clock = time.fromisoformat(clock_text)
    return pd.Timestamp(datetime.combine(trade_date, clock, tzinfo=SHANGHAI))


def _prepare_features(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(FEATURE_COLUMNS).difference(frame.columns)
    if missing:
        raise SnapshotBuildError(f"feature frame missing columns: {sorted(missing)}")
    result = frame.loc[:, FEATURE_COLUMNS].copy()
    result["symbol"] = result["symbol"].map(normalize_symbol)
    if result["symbol"].duplicated().any():
        raise SnapshotBuildError("feature frame contains duplicate symbols")
    return result.set_index("symbol", drop=False)


def _security_audit_row(master_row: pd.Series) -> dict[str, object]:
    return {
        "source": f"security_master:{master_row['source']}",
        "source_timestamp": master_row["source_timestamp"],
        "feature_available_at": master_row["available_at"],
        "fetched_at": master_row["fetched_at"],
    }


def _empty_market_fields() -> dict[str, object]:
    values: dict[str, object] = {name: pd.NA for name in _REQUIRED_TRADABLE_FEATURES}
    values["volume_unit"] = "unavailable"
    values["turnover_unit"] = "unavailable"
    values["industry_id"] = pd.NA
    values["market_context"] = pd.NA
    return values


def build_decision_slice(
    *,
    master: PointInTimeSecurityMaster,
    trade_date: date,
    decision_clock: str,
    universe_symbols: Sequence[str],
    features: pd.DataFrame,
) -> pd.DataFrame:
    decision_ts = decision_timestamp(trade_date, decision_clock)
    symbols = tuple(normalize_symbol(symbol) for symbol in universe_symbols)
    if not symbols:
        raise SnapshotBuildError("universe_symbols cannot be empty")
    if len(set(symbols)) != len(symbols):
        raise SnapshotBuildError("universe_symbols contains duplicates")

    feature_rows = _prepare_features(features)
    security = master.as_of(decision_ts, knowledge_cutoff=decision_ts).set_index("symbol", drop=False)
    missing_master = [symbol for symbol in symbols if symbol not in security.index]
    if missing_master:
        raise SnapshotBuildError(
            f"point-in-time security master missing universe symbols: {missing_master}"
        )

    rows: list[dict[str, object]] = []
    for symbol in symbols:
        sm = security.loc[symbol]
        row: dict[str, object] = {
            "trade_date": trade_date,
            "symbol": symbol,
            "decision_ts": decision_ts,
            "security_master_asof": sm["available_at"],
            "feature_schema_version": DECISION_SNAPSHOT_SCHEMA_VERSION,
        }
        market = feature_rows.loc[symbol] if symbol in feature_rows.index else None
        if market is None:
            row.update(_empty_market_fields())
            row.update(_security_audit_row(sm))
            row["tradable"] = False
            row["unavailable_reason"] = "MISSING_MARKET_DATA"
        else:
            for field in FEATURE_COLUMNS:
                if field != "symbol":
                    row[field] = market[field]
            incomplete = any(pd.isna(market[field]) for field in _REQUIRED_TRADABLE_FEATURES)
            is_st = bool(sm["is_st"]) if not pd.isna(sm["is_st"]) else False
            is_suspended = (
                bool(sm["is_suspended"]) if not pd.isna(sm["is_suspended"]) else False
            ) or str(sm["status"]) == "SUSPENDED"
            if is_st:
                row["tradable"] = False
                row["unavailable_reason"] = "ST"
            elif is_suspended:
                row["tradable"] = False
                row["unavailable_reason"] = "SUSPENDED"
            elif incomplete:
                row["tradable"] = False
                row["unavailable_reason"] = "INCOMPLETE_MARKET_DATA"
            else:
                row["tradable"] = True
                row["unavailable_reason"] = ""
        rows.append(row)
    return pd.DataFrame(rows, columns=DECISION_SNAPSHOT_COLUMNS)


def build_full_universe_snapshot_cube(
    *,
    master: PointInTimeSecurityMaster,
    trade_date: date,
    feature_frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    missing_clocks = set(DECISION_CLOCKS).difference(feature_frames)
    extra_clocks = set(feature_frames).difference(DECISION_CLOCKS)
    if missing_clocks or extra_clocks:
        raise SnapshotBuildError(
            f"feature_frames clocks mismatch: missing={sorted(missing_clocks)}, extra={sorted(extra_clocks)}"
        )
    first_ts = decision_timestamp(trade_date, DECISION_CLOCKS[0])
    universe = master.universe(first_ts, knowledge_cutoff=first_ts)
    symbols = tuple(universe["symbol"].map(normalize_symbol))
    if not symbols:
        raise SnapshotBuildError("point-in-time universe is empty")
    slices = [
        build_decision_slice(
            master=master,
            trade_date=trade_date,
            decision_clock=clock,
            universe_symbols=symbols,
            features=feature_frames[clock],
        )
        for clock in DECISION_CLOCKS
    ]
    cube = pd.concat(slices, ignore_index=True)
    return validate_decision_snapshot_frame(cube, universe_symbols=symbols)
