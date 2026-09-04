from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from xalpha.data.base import DataAudit, DataBatch
from xalpha.data.benchmark import benchmark_provider_call, observation_json_record

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_benchmark_records_request_and_staleness():
    times = iter(
        [
            datetime(2026, 9, 4, 14, 50, 0, tzinfo=SHANGHAI),
            datetime(2026, 9, 4, 14, 50, 2, tzinfo=SHANGHAI),
        ]
    )

    def clock():
        return next(times)

    fetched_at = datetime(2026, 9, 4, 14, 50, 1, tzinfo=SHANGHAI)
    source_time = fetched_at - timedelta(seconds=30)
    batch = DataBatch(
        raw=pd.DataFrame({"x": [1]}),
        normalized=pd.DataFrame({"x": [1]}),
        audit=DataAudit(
            dataset="snapshot",
            source="fixture",
            endpoint="fixture",
            params={},
            source_timestamp=source_time,
            fetched_at=fetched_at,
            schema_version="TEST",
            availability_policy="verified",
        ),
    )

    returned, observation = benchmark_provider_call(
        provider="fixture",
        dataset="snapshot",
        call=lambda: batch,
        clock=clock,
    )
    assert returned is batch
    assert observation.request_latency_seconds == 2.0
    record = observation_json_record(observation)
    assert record["freshness_status"] == "FRESH"
    assert record["success"] is True
