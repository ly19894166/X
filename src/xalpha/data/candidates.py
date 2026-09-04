from __future__ import annotations

import importlib
from collections.abc import Callable
from datetime import datetime
from types import ModuleType
from zoneinfo import ZoneInfo

import pandas as pd

from ..universe import normalize_symbol
from .base import DataAudit, DataBatch

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _default_clock() -> datetime:
    return datetime.now(tz=SHANGHAI)


def _client_or_import(client: object | None) -> ModuleType | object:
    if client is not None:
        return client
    return importlib.import_module("akshare")


def _column(frame: pd.DataFrame, *names: str, required: bool = True) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    if required:
        raise ValueError(f"provider response missing columns {names!r}")
    return None


def _aware(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None:
        raise ValueError("clock must be timezone-aware")
    return value.astimezone(SHANGHAI)


def _sina_symbol(symbol: str) -> str:
    code = normalize_symbol(symbol)
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("4", "8", "920")):
        return f"bj{code}"
    return f"sz{code}"


class EastMoneySnapshotCandidate:
    """Current full-market snapshot candidate via AKShare/EastMoney.

    The endpoint does not expose a provider event timestamp that X has
    independently verified. Therefore ``source_timestamp`` remains ``None`` and
    this adapter is intentionally not decision-eligible until qualification.
    """

    source = "akshare_eastmoney"
    endpoint = "stock_zh_a_spot_em"

    def __init__(self, *, client: object | None = None, clock: Callable[[], datetime] = _default_clock):
        self._client = client
        self._clock = clock

    def fetch_full_market_snapshot(self) -> DataBatch:
        fetched_at = _aware(self._clock)
        client = _client_or_import(self._client)
        raw = getattr(client, self.endpoint)()
        if not isinstance(raw, pd.DataFrame):
            raise TypeError("stock_zh_a_spot_em did not return DataFrame")

        mapping = {
            "symbol": ("代码", "code", "symbol"),
            "name": ("名称", "name"),
            "price": ("最新价", "price", "close"),
            "open": ("今开", "open"),
            "high": ("最高", "high"),
            "low": ("最低", "low"),
            "prev_close": ("昨收", "prev_close"),
            "volume": ("成交量", "volume"),
            "turnover": ("成交额", "amount", "turnover"),
            "change_pct": ("涨跌幅", "change_pct"),
            "turnover_rate": ("换手率", "turnover_rate"),
        }
        normalized = pd.DataFrame(index=raw.index)
        for target, candidates in mapping.items():
            col = _column(raw, *candidates, required=target not in {"turnover_rate"})
            if col is None:
                normalized[target] = pd.NA
            elif target in {"symbol", "name"}:
                normalized[target] = raw[col]
            else:
                normalized[target] = pd.to_numeric(raw[col], errors="coerce")
        normalized["symbol"] = normalized["symbol"].map(normalize_symbol)
        normalized["name"] = normalized["name"].astype("string").str.strip()
        if normalized["symbol"].duplicated().any():
            raise ValueError("full-market snapshot contains duplicate symbols")
        normalized["provider_timestamp"] = pd.NaT
        normalized["source_timestamp"] = pd.NaT
        normalized["fetched_at"] = fetched_at
        normalized["availability_verified"] = False
        normalized["source"] = self.source
        normalized["schema_version"] = "X_FULL_MARKET_SNAPSHOT_V0.1"

        audit = DataAudit(
            dataset="full_market_snapshot",
            source=self.source,
            endpoint=self.endpoint,
            params={},
            source_timestamp=None,
            fetched_at=fetched_at,
            schema_version="X_FULL_MARKET_SNAPSHOT_V0.1",
            units={"volume": "provider_native_unverified", "turnover": "CNY_unverified"},
            availability_policy="provider_event_time_unverified",
        )
        batch = DataBatch(raw=raw.copy(), normalized=normalized.reset_index(drop=True), audit=audit)
        batch.validate()
        return batch


class SinaMinuteCandidate:
    """Backup minute candidate via AKShare/Sina.

    Provider timestamps are preserved, but their bar-start/bar-end semantics and
    publication delay are not assumed. DataAudit.source_timestamp therefore
    remains None until a qualification run proves those semantics.
    """

    source = "akshare_sina"
    endpoint = "stock_zh_a_minute"

    def __init__(self, *, client: object | None = None, clock: Callable[[], datetime] = _default_clock):
        self._client = client
        self._clock = clock

    def fetch_minute_bars(self, symbol: str, *, period: str = "1", adjust: str = "") -> DataBatch:
        if period not in {"1", "5", "15", "30", "60"}:
            raise ValueError("unsupported period")
        fetched_at = _aware(self._clock)
        client = _client_or_import(self._client)
        params = {"symbol": _sina_symbol(symbol), "period": period, "adjust": adjust}
        raw = getattr(client, self.endpoint)(**params)
        if not isinstance(raw, pd.DataFrame):
            raise TypeError("stock_zh_a_minute did not return DataFrame")

        time_col = _column(raw, "day", "时间", "datetime", "timestamp")
        timestamps = pd.to_datetime(raw[time_col], errors="coerce")
        if timestamps.isna().any():
            raise ValueError("Sina minute response contains invalid timestamps")
        if timestamps.dt.tz is None:
            timestamps = timestamps.dt.tz_localize(SHANGHAI)
        else:
            timestamps = timestamps.dt.tz_convert(SHANGHAI)

        normalized = pd.DataFrame({"provider_timestamp": timestamps})
        for target, names in {
            "open": ("open", "开盘"),
            "high": ("high", "最高"),
            "low": ("low", "最低"),
            "close": ("close", "收盘"),
            "volume": ("volume", "成交量"),
        }.items():
            col = _column(raw, *names)
            normalized[target] = pd.to_numeric(raw[col], errors="coerce")
        normalized["turnover"] = pd.NA
        normalized["symbol"] = normalize_symbol(symbol)
        normalized["period_minutes"] = int(period)
        normalized["source_timestamp"] = pd.NaT
        normalized["available_at"] = pd.NaT
        normalized["availability_verified"] = False
        normalized["volume_unit"] = "provider_native_unverified"
        normalized["turnover_unit"] = "not_provided"
        normalized["fetched_at"] = fetched_at
        normalized["source"] = self.source
        normalized["schema_version"] = "X_MINUTE_BAR_V0.1"

        audit = DataAudit(
            dataset="minute_bars",
            source=self.source,
            endpoint=self.endpoint,
            params=params,
            source_timestamp=None,
            fetched_at=fetched_at,
            schema_version="X_MINUTE_BAR_V0.1",
            units={"volume": "provider_native_unverified", "turnover": "not_provided"},
            availability_policy="minute_timestamp_semantics_unverified",
        )
        batch = DataBatch(raw=raw.copy(), normalized=normalized, audit=audit)
        batch.validate()
        return batch
