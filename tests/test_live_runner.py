from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from xalpha.data.base import DataAudit, DataBatch
from xalpha.live_runner import BenchmarkTask, LiveBenchmarkRunner

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_live_runner_records_cycle_and_jsonl(tmp_path):
    base = datetime(2026, 9, 7, 14, 50, 0, tzinfo=SHANGHAI)
    times = iter([base, base, base + timedelta(seconds=2), base + timedelta(seconds=3)])

    def clock():
        return next(times)

    batch = DataBatch(
        raw=pd.DataFrame({"x": [1]}),
        normalized=pd.DataFrame({"x": [1]}),
        audit=DataAudit(
            dataset="snapshot",
            source="fixture",
            endpoint="fixture",
            params={},
            source_timestamp=base - timedelta(seconds=20),
            fetched_at=base + timedelta(seconds=1),
            schema_version="TEST",
            availability_policy="verified",
        ),
    )
    path = tmp_path / "bench.jsonl"
    runner = LiveBenchmarkRunner(clock=clock, observation_path=path)
    cycle = runner.run_once(
        [BenchmarkTask(name="snapshot", provider="fixture", dataset="snapshot", call=lambda: batch)]
    )
    assert set(cycle.batches) == {"snapshot"}
    assert len(cycle.observations) == 1
    assert cycle.observations[0].success is True
    assert "FRESH" in path.read_text(encoding="utf-8")
