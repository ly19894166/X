from __future__ import annotations

import time as time_module
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from .data.base import DataBatch
from .data.benchmark import append_observation_jsonl, benchmark_provider_call
from .data.qualification import FreshnessPolicy, ProviderObservation

SHANGHAI = ZoneInfo("Asia/Shanghai")
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
ProviderCall = Callable[[], DataBatch]


@dataclass(frozen=True)
class BenchmarkTask:
    name: str
    provider: str
    dataset: str
    call: ProviderCall
    symbol: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("benchmark task name is required")
        if not self.provider.strip():
            raise ValueError("benchmark task provider is required")
        if not self.dataset.strip():
            raise ValueError("benchmark task dataset is required")


@dataclass(frozen=True)
class BenchmarkCycle:
    started_at: datetime
    finished_at: datetime
    batches: Mapping[str, DataBatch]
    observations: tuple[ProviderObservation, ...]


class LiveBenchmarkRunner:
    """Run provider qualification calls without turning failures into market data.

    The runner is deliberately provider-neutral. During live use each cycle can
    contain a full-market snapshot task plus one or more minute-bar probes. In
    CI the same runner is exercised with deterministic replay fixtures.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        policy: FreshnessPolicy | None = None,
        observation_path: str | Path | None = None,
    ) -> None:
        self.clock = clock
        self.policy = policy or FreshnessPolicy()
        self.observation_path = None if observation_path is None else Path(observation_path)

    def run_once(self, tasks: Sequence[BenchmarkTask]) -> BenchmarkCycle:
        if not tasks:
            raise ValueError("at least one benchmark task is required")
        started_at = self.clock()
        if started_at.tzinfo is None:
            raise ValueError("benchmark clock must be timezone-aware")
        batches: dict[str, DataBatch] = {}
        observations: list[ProviderObservation] = []
        seen: set[str] = set()
        for task in tasks:
            task.validate()
            if task.name in seen:
                raise ValueError(f"duplicate benchmark task name: {task.name}")
            seen.add(task.name)
            batch, observation = benchmark_provider_call(
                provider=task.provider,
                dataset=task.dataset,
                call=task.call,
                clock=self.clock,
                symbol=task.symbol,
            )
            observations.append(observation)
            if batch is not None:
                batches[task.name] = batch
            if self.observation_path is not None:
                append_observation_jsonl(
                    self.observation_path,
                    observation,
                    policy=self.policy,
                )
        finished_at = self.clock()
        return BenchmarkCycle(
            started_at=started_at,
            finished_at=finished_at,
            batches=batches,
            observations=tuple(observations),
        )

    def run_schedule(
        self,
        tasks: Sequence[BenchmarkTask],
        *,
        trade_date: date,
        clocks: Sequence[str] = ("14:35", "14:45", "14:50"),
        sleeper: Sleeper = time_module.sleep,
    ) -> tuple[BenchmarkCycle, ...]:
        """Wait for each requested Shanghai clock and execute one benchmark cycle.

        Past clocks are skipped rather than replayed with current data. This is
        important: a 14:50 call made at 15:20 must never be presented as a real
        14:50 live observation.
        """

        cycles: list[BenchmarkCycle] = []
        for clock_text in clocks:
            parsed = time.fromisoformat(clock_text)
            target = datetime.combine(trade_date, parsed, tzinfo=SHANGHAI)
            now = self.clock().astimezone(SHANGHAI)
            if now > target:
                continue
            wait_seconds = (target - now).total_seconds()
            if wait_seconds > 0:
                sleeper(wait_seconds)
            cycles.append(self.run_once(tasks))
        return tuple(cycles)
