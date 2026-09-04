from datetime import datetime

import pytest

from xalpha.domain import DecisionSnapshot
from xalpha.integrity import assert_no_future_features


def test_snapshot_rejects_future_source():
    snap = DecisionSnapshot(
        trade_date="2026-09-04",
        symbol="600000",
        decision_ts=datetime(2026, 9, 4, 14, 50),
        price=10.0,
        source="demo",
        source_timestamp=datetime(2026, 9, 4, 14, 51),
    )
    with pytest.raises(ValueError, match="future leakage"):
        snap.validate()


def test_feature_gate_rejects_future_timestamp():
    decision = datetime(2026, 9, 4, 14, 50)
    with pytest.raises(ValueError, match="future leakage"):
        assert_no_future_features(decision, [datetime(2026, 9, 4, 14, 49), datetime(2026, 9, 4, 15, 0)])
