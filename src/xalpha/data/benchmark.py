from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import DataBatch
from .qualification import FreshnessPolicy, ProviderObservation

Clock = Callable[[], datetime]
ProviderCall = Callable[[], DataBatch]


def benchmark_provider_call(
    *,
    provider: str,
    dataset: str,
    call: ProviderCall,
    clock: Clock,
    symbol: str = "",
) -> tuple[DataBatch | None, ProviderObservation]:
    requested_at = clock()
    if requested_at.tzinfo is None:
        raise ValueError("benchmark clock must be timezone-aware")
    try:
        batch = call()
        received_at = clock()
        batch.validate()
        observation = ProviderObservation(
            provider=provider,
            dataset=dataset,
            symbol=symbol,
            requested_at=requested_at,
            received_at=received_at,
            success=True,
            event_time=batch.audit.source_timestamp,
            provider_time=batch.audit.source_timestamp,
            row_count=int(len(batch.normalized)),
        )
        observation.validate()
        return batch, observation
    except Exception as exc:
        received_at = clock()
        name = type(exc).__name__
        lowered = name.lower()
        observation = ProviderObservation(
            provider=provider,
            dataset=dataset,
            symbol=symbol,
            requested_at=requested_at,
            received_at=received_at,
            success=False,
            timeout="timeout" in lowered,
            parse_error=(
                "parse" in lowered
                or "decode" in lowered
                or name in {"ValueError", "KeyError"}
            ),
            row_count=0,
            error_type=name,
            error_message=str(exc),
        )
        observation.validate()
        return None, observation


def observation_json_record(
    observation: ProviderObservation,
    *,
    policy: FreshnessPolicy | None = None,
) -> dict[str, Any]:
    record = observation.as_record(policy or FreshnessPolicy())
    for key, value in list(record.items()):
        if isinstance(value, datetime):
            record[key] = value.isoformat()
    return record


def append_observation_jsonl(
    path: str | Path,
    observation: ProviderObservation,
    *,
    policy: FreshnessPolicy | None = None,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        observation_json_record(observation, policy=policy),
        ensure_ascii=False,
        sort_keys=True,
    )
    with target.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
