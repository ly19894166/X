"""Independent, audited market-data interfaces for X."""

from .akshare import AKShareAdapter, AKShareDataError, MissingAKShareDependency
from .base import DataAudit, DataBatch, MarketDataAdapter
from .cache import (
    AuditedLocalCache,
    CacheCollisionError,
    CacheEntry,
    CacheIntegrityError,
)

__all__ = [
    "AKShareAdapter",
    "AKShareDataError",
    "AuditedLocalCache",
    "CacheCollisionError",
    "CacheEntry",
    "CacheIntegrityError",
    "DataAudit",
    "DataBatch",
    "MarketDataAdapter",
    "MissingAKShareDependency",
]
