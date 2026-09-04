from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, fields
from datetime import date

import pandas as pd

from .domain import NextMorningOutcome
from .labels import compute_next_morning_outcome
from .snapshots import validate_decision_snapshot_frame

MinuteLoader = Callable[[str, date], pd.DataFrame]
OUTCOME_COLUMNS = tuple(field.name for field in fields(NextMorningOutcome))
SETTLEMENT_KEY = ("trade_date", "symbol", "decision_ts")


class SettlementError(ValueError):
    pass


def _market_open_price(raw: pd.DataFrame) -> float | None:
    if "timestamp" not in raw.columns or "open" not in raw.columns:
        return None
    frame = raw.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    exact = frame[frame["timestamp"].dt.strftime("%H:%M") == "09:30"]
    if exact.empty:
        return None
    value = pd.to_numeric(exact.iloc[-1]["open"], errors="coerce")
    if pd.isna(value) or float(value) <= 0:
        return None
    return float(value)


def _empty_outcome() -> dict[str, object]:
    return {column: pd.NA for column in OUTCOME_COLUMNS}


def settle_snapshot_cube(
    snapshot_cube: pd.DataFrame,
    *,
    next_trade_date: date,
    minute_loader: MinuteLoader,
) -> pd.DataFrame:
    """Settle every decision-time sample while loading T+1 morning data once per symbol."""

    symbols = tuple(sorted(set(snapshot_cube["symbol"].astype(str))))
    cube = validate_decision_snapshot_frame(snapshot_cube, universe_symbols=symbols)
    trade_dates = set(cube["trade_date"])
    if len(trade_dates) != 1:
        raise SettlementError("snapshot cube must contain one trade_date")
    trade_date = next(iter(trade_dates))
    if next_trade_date <= trade_date:
        raise SettlementError("next_trade_date must be later than snapshot trade_date")

    morning_cache: dict[str, pd.DataFrame | Exception] = {}
    for symbol in symbols:
        try:
            morning_cache[symbol] = minute_loader(symbol, next_trade_date)
        except Exception as exc:  # preserve denominator; do not delete failed symbols
            morning_cache[symbol] = exc

    rows: list[dict[str, object]] = []
    for snapshot in cube.itertuples(index=False):
        base: dict[str, object] = {
            "trade_date": snapshot.trade_date,
            "symbol": snapshot.symbol,
            "decision_ts": snapshot.decision_ts,
            "entry_price": snapshot.price,
            "next_trade_date": next_trade_date,
            "settlement_status": "",
            "settlement_error": "",
        }
        if not snapshot.tradable:
            base.update(_empty_outcome())
            base["settlement_status"] = "NOT_ELIGIBLE_ENTRY"
            rows.append(base)
            continue

        morning = morning_cache[snapshot.symbol]
        if isinstance(morning, Exception):
            base.update(_empty_outcome())
            base["settlement_status"] = "MISSING_T1_DATA"
            base["settlement_error"] = f"{type(morning).__name__}: {morning}"
            rows.append(base)
            continue

        try:
            outcome = compute_next_morning_outcome(
                morning,
                entry_price=float(snapshot.price),
                market_open_price=_market_open_price(morning),
            )
            base.update(asdict(outcome))
            base["settlement_status"] = "SETTLED"
        except Exception as exc:
            base.update(_empty_outcome())
            base["settlement_status"] = "INVALID_T1_DATA"
            base["settlement_error"] = f"{type(exc).__name__}: {exc}"
        rows.append(base)

    result = pd.DataFrame(rows)
    if result.duplicated(list(SETTLEMENT_KEY)).any():
        raise SettlementError("settlement produced duplicate keys")
    return result.sort_values(["decision_ts", "symbol"]).reset_index(drop=True)


def build_training_table(snapshot_cube: pd.DataFrame, settlement: pd.DataFrame) -> pd.DataFrame:
    required = set(SETTLEMENT_KEY).union({"settlement_status"})
    missing = required.difference(settlement.columns)
    if missing:
        raise SettlementError(f"settlement missing columns: {sorted(missing)}")
    if settlement.duplicated(list(SETTLEMENT_KEY)).any():
        raise SettlementError("settlement keys are not unique")
    merged = snapshot_cube.merge(
        settlement,
        on=list(SETTLEMENT_KEY),
        how="left",
        validate="one_to_one",
        suffixes=("", "_settled"),
    )
    if merged["settlement_status"].isna().any():
        raise SettlementError("training table has un-settled snapshot rows")
    return merged.sort_values(["decision_ts", "symbol"]).reset_index(drop=True)
