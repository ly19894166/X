from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class DataAudit:
    """Immutable provenance attached to one provider response.

    ``source_timestamp`` describes the newest source event represented by the
    response. ``fetched_at`` describes when X retrieved it. They deliberately
    remain separate because a historical fetch may happen long after a valid
    decision time.
    """

    dataset: str
    source: str
    endpoint: str
    params: Mapping[str, Any]
    source_timestamp: datetime | None
    fetched_at: datetime
    schema_version: str
    units: Mapping[str, str] = field(default_factory=dict)
    availability_policy: str = "unverified"

    def validate(self) -> None:
        if not self.dataset.strip():
            raise ValueError("audit dataset is required")
        if not self.source.strip():
            raise ValueError("audit source is required")
        if not self.endpoint.strip():
            raise ValueError("audit endpoint is required")
        if not self.schema_version.strip():
            raise ValueError("audit schema_version is required")
        if self.fetched_at.tzinfo is None:
            raise ValueError("audit fetched_at must be timezone-aware")
        if self.source_timestamp is not None:
            if self.source_timestamp.tzinfo is None:
                raise ValueError("audit source_timestamp must be timezone-aware")
            if self.source_timestamp > self.fetched_at:
                raise ValueError("source_timestamp cannot be later than fetched_at")


@dataclass(frozen=True)
class DataBatch:
    """Raw provider rows, canonical rows, and the audit binding between them."""

    raw: pd.DataFrame
    normalized: pd.DataFrame
    audit: DataAudit

    def validate(self) -> None:
        self.audit.validate()
        if not isinstance(self.raw, pd.DataFrame):
            raise TypeError("raw must be a pandas DataFrame")
        if not isinstance(self.normalized, pd.DataFrame):
            raise TypeError("normalized must be a pandas DataFrame")


@runtime_checkable
class MarketDataAdapter(Protocol):
    """Provider-neutral surface used by X data ingestion."""

    source: str

    def fetch_trading_calendar(self) -> DataBatch: ...

    def fetch_current_security_master(self) -> DataBatch: ...

    def fetch_daily_bars(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        adjust: str = "",
    ) -> DataBatch: ...

    def fetch_minute_bars(
        self,
        symbol: str,
        *,
        start: str,
        end: str,
        period: str = "1",
        adjust: str = "",
    ) -> DataBatch: ...
