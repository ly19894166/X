import pandas as pd

from xalpha.labels import compute_next_morning_outcome


def _frame():
    ts = pd.date_range("2026-09-07 09:31", "2026-09-07 10:00", freq="1min")
    close = [10.00 + i * 0.01 for i in range(len(ts))]
    frame = pd.DataFrame({
        "timestamp": ts,
        "open": close,
        "high": [x + 0.02 for x in close],
        "low": [x - 0.02 for x in close],
        "close": close,
    })
    return frame


def test_outcome_fixed_points_and_path():
    result = compute_next_morning_outcome(_frame(), entry_price=10.0, market_open_price=10.0)
    assert result.next_0935_return > 0
    assert result.next_0945_return > result.next_0935_return
    assert result.hit_plus_1_0 is True
    assert result.plus1_before_minus1 == "UP_FIRST"
    assert result.open30_mfe >= result.next_1000_return


def test_same_bar_touch_is_ambiguous():
    frame = _frame()
    frame.loc[0, "high"] = 10.2
    frame.loc[0, "low"] = 9.8
    result = compute_next_morning_outcome(frame, entry_price=10.0)
    assert result.plus1_before_minus1 == "AMBIGUOUS"
