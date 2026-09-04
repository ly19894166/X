from __future__ import annotations

import math
from datetime import time

import pandas as pd

from .domain import NextMorningOutcome, PathOutcome


_REQUIRED = {"timestamp", "open", "high", "low", "close"}


def _ret(price: float, entry: float) -> float:
    return price / entry - 1.0


def _clock(text: str) -> time:
    return pd.Timestamp(text).time()


def _exact_close(frame: pd.DataFrame, clock: str) -> float:
    rows = frame[frame["timestamp"].dt.time == _clock(clock)]
    if rows.empty:
        raise ValueError(f"missing critical minute: {clock}")
    return float(rows.iloc[-1]["close"])


def _first_touch(frame: pd.DataFrame, entry: float, pct: float, up: bool) -> str | None:
    level = entry * (1.0 + pct if up else 1.0 - pct)
    rows = frame[frame["high"] >= level] if up else frame[frame["low"] <= level]
    if rows.empty:
        return None
    return rows.iloc[0]["timestamp"].strftime("%H:%M")


def _path_outcome(up_time: str | None, down_time: str | None) -> PathOutcome:
    if up_time and down_time:
        if up_time == down_time:
            return "AMBIGUOUS"
        return "UP_FIRST" if up_time < down_time else "DOWN_FIRST"
    if up_time:
        return "UP_FIRST"
    if down_time:
        return "DOWN_FIRST"
    return "NEITHER"


def _peak_to_trough_drawdown(frame: pd.DataFrame) -> float:
    running_peak = -math.inf
    worst = 0.0
    for row in frame.itertuples(index=False):
        running_peak = max(running_peak, float(row.high))
        if running_peak > 0:
            worst = min(worst, float(row.low) / running_peak - 1.0)
    return worst


def normalize_morning_frame(raw: pd.DataFrame, *, window_start: str = "09:31", window_end: str = "10:00") -> pd.DataFrame:
    missing = _REQUIRED.difference(raw.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    frame = raw.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    for col in ("open", "high", "low", "close"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=list(_REQUIRED)).sort_values("timestamp")
    frame = frame.drop_duplicates("timestamp", keep="last")
    frame = frame[
        frame["timestamp"].dt.time.between(_clock(window_start), _clock(window_end))
    ].reset_index(drop=True)
    if frame.empty:
        raise ValueError("morning window is empty")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC must be positive")
    return frame


def compute_next_morning_outcome(raw: pd.DataFrame, *, entry_price: float, market_open_price: float | None = None) -> NextMorningOutcome:
    if not math.isfinite(entry_price) or entry_price <= 0:
        raise ValueError("entry_price must be positive")
    frame = normalize_morning_frame(raw)

    p0935 = _exact_close(frame, "09:35")
    p0945 = _exact_close(frame, "09:45")
    p1000 = _exact_close(frame, "10:00")

    highest_idx = frame["high"].idxmax()
    lowest_idx = frame["low"].idxmin()
    highest = float(frame.loc[highest_idx, "high"])
    lowest = float(frame.loc[lowest_idx, "low"])

    up05 = _first_touch(frame, entry_price, 0.005, True)
    up10 = _first_touch(frame, entry_price, 0.010, True)
    up15 = _first_touch(frame, entry_price, 0.015, True)
    dn05 = _first_touch(frame, entry_price, 0.005, False)
    dn10 = _first_touch(frame, entry_price, 0.010, False)

    open_ret = None
    if market_open_price is not None:
        if not math.isfinite(market_open_price) or market_open_price <= 0:
            raise ValueError("market_open_price must be positive when provided")
        open_ret = _ret(market_open_price, entry_price)

    return NextMorningOutcome(
        next_open_return=open_ret,
        next_0935_return=_ret(p0935, entry_price),
        next_0945_return=_ret(p0945, entry_price),
        next_1000_return=_ret(p1000, entry_price),
        open30_mfe=_ret(highest, entry_price),
        open30_mae=_ret(lowest, entry_price),
        peak_to_trough_drawdown=_peak_to_trough_drawdown(frame),
        hit_plus_0_5=up05 is not None,
        hit_plus_1_0=up10 is not None,
        hit_plus_1_5=up15 is not None,
        hit_minus_0_5=dn05 is not None,
        hit_minus_1_0=dn10 is not None,
        first_touch_plus_1=up10,
        first_touch_minus_1=dn10,
        plus1_before_minus1=_path_outcome(up10, dn10),
        time_to_mfe=frame.loc[highest_idx, "timestamp"].strftime("%H:%M"),
        time_to_mae=frame.loc[lowest_idx, "timestamp"].strftime("%H:%M"),
    )
