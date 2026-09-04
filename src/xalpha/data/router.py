from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from .base import DataBatch
from .qualification import FreshnessPolicy, FreshnessStatus

ProviderRole = Literal["PRIMARY", "BACKUP", "CACHE"]
ProviderCall = Callable[[], DataBatch]


class ProviderRouteError(RuntimeError):
    def __init__(self, message: str, *, attempts: Sequence["RouteAttempt"]):
        super().__init__(message)
        self.attempts = tuple(attempts)


@dataclass(frozen=True)
class RouteAttempt:
    role: ProviderRole
    provider: str
    success: bool
    freshness_status: FreshnessStatus = FreshnessStatus.UNKNOWN
    staleness_seconds: float | None = None
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class RouteResult:
    batch: DataBatch
    selected_role: ProviderRole
    freshness_status: FreshnessStatus
    staleness_seconds: float | None
    attempts: tuple[RouteAttempt, ...]


def _freshness_for_batch(
    batch: DataBatch,
    *,
    policy: FreshnessPolicy,
    require_source_timestamp: bool,
) -> tuple[FreshnessStatus, float | None]:
    batch.validate()
    source_time = batch.audit.source_timestamp
    if source_time is None:
        if require_source_timestamp:
            return FreshnessStatus.UNKNOWN, None
        return FreshnessStatus.FRESH, None
    staleness = max(0.0, (batch.audit.fetched_at - source_time).total_seconds())
    return policy.classify_seconds(staleness), staleness


def route_data_batch(
    *,
    primary: ProviderCall,
    backups: Sequence[ProviderCall] = (),
    cache_loader: ProviderCall | None = None,
    policy: FreshnessPolicy | None = None,
    require_source_timestamp: bool = True,
) -> RouteResult:
    """Try Primary -> Backup(s) -> Cache and fail closed if none qualify.

    Provider exceptions are recorded but never converted into synthetic market
    data. A response that is too stale is also rejected even if the network call
    itself succeeded.
    """

    active_policy = policy or FreshnessPolicy()
    attempts: list[RouteAttempt] = []
    plan: list[tuple[ProviderRole, ProviderCall]] = [("PRIMARY", primary)]
    plan.extend(("BACKUP", call) for call in backups)
    if cache_loader is not None:
        plan.append(("CACHE", cache_loader))

    for role, call in plan:
        provider_name = getattr(call, "provider_name", getattr(call, "__name__", role.lower()))
        try:
            batch = call()
            status, staleness = _freshness_for_batch(
                batch,
                policy=active_policy,
                require_source_timestamp=require_source_timestamp,
            )
            eligible = active_policy.decision_eligible(status)
            attempts.append(
                RouteAttempt(
                    role=role,
                    provider=str(batch.audit.source or provider_name),
                    success=eligible,
                    freshness_status=status,
                    staleness_seconds=staleness,
                    error_type="" if eligible else "FreshnessRejected",
                    error_message="" if eligible else f"freshness={status.value}",
                )
            )
            if eligible:
                return RouteResult(
                    batch=batch,
                    selected_role=role,
                    freshness_status=status,
                    staleness_seconds=staleness,
                    attempts=tuple(attempts),
                )
        except Exception as exc:
            attempts.append(
                RouteAttempt(
                    role=role,
                    provider=str(provider_name),
                    success=False,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )

    detail = "; ".join(
        f"{item.role}:{item.provider}:{item.error_type or item.freshness_status.value}"
        for item in attempts
    )
    raise ProviderRouteError(
        f"no provider produced decision-eligible data ({detail})",
        attempts=attempts,
    )
