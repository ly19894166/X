from __future__ import annotations

import importlib
from collections.abc import Callable
from datetime import datetime, time, timedelta
from types import ModuleType
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

from ..universe import classify_board, normalize_symbol
from .base import DataAudit, DataBatch

SHANGHAI = ZoneInfo("Asia/Shanghai")
MinuteTimestampSemantics = Literal["bar_start", "bar_end", "unverified"]


class MissingAKShareDependency(RuntimeError):
    pass


class AKShareDataError(RuntimeError):
    pass


def _default_clock() -> datetime:
    return datetime.now(tz=SHANGHAI)


def _aware_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(SHANGHAI)


def _column(frame: pd.DataFrame, *candidates: str, required: bool = True) -> str | None:
    for name in candidates:
        if name in frame.columns:
            return name
    if required:
        raise AKShareDataError(f"AKShare response missing columns {candidates!r}")
    return None


def _require_frame(value: object, *, endpoint: str) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise AKShareDataError(f"{endpoint} did not return a pandas DataFrame")
    return value


def _validate_bars(frame: pd.DataFrame, *, dataset: str) -> None:
    prices = frame[["open", "high", "low", "close"]]
    if (prices <= 0).any().any():
        raise AKShareDataError(f"{dataset} contains non-positive OHLC values")
    invalid_high = frame["high"] < prices[["open", "close", "low"]].max(axis=1)
    invalid_low = frame["low"] > prices[["open", "close", "high"]].min(axis=1)
    if invalid_high.any() or invalid_low.any():
        raise AKShareDataError(f"{dataset} contains inconsistent OHLC values")
    if (frame[["volume", "turnover"]] < 0).any().any():
        raise AKShareDataError(f"{dataset} contains negative volume or turnover")


def _local_timestamps(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.isna().any():
        raise AKShareDataError("AKShare response contains invalid timestamps")
    if parsed.dt.tz is None:
        return parsed.dt.tz_localize(SHANGHAI)
    return parsed.dt.tz_convert(SHANGHAI)


def _exchange(symbol: str) -> str:
    if symbol.startswith("6"):
        return "SSE"
    if symbol.startswith(("4", "8", "920")):
        return "BSE"
    return "SZSE"


class AKShareAdapter:
    """AKShare boundary with explicit schemas and no import-time dependency.

    The adapter preserves every provider response in ``DataBatch.raw``. It does
    not guess the unit of AKShare's minute ``成交量`` field. Consumers must use
    ``volume_unit`` and may only derive share-based VWAP after a unit policy has
    been independently verified.
    """

    source = "akshare"

    def __init__(
        self,
        *,
        client: ModuleType | object | None = None,
        clock: Callable[[], datetime] = _default_clock,
        minute_timestamp_semantics: MinuteTimestampSemantics = "unverified",
        minute_publication_lag: timedelta = timedelta(0),
        minute_volume_unit: str = "provider_native_unverified",
    ):
        if minute_timestamp_semantics not in {"bar_start", "bar_end", "unverified"}:
            raise ValueError("unsupported minute timestamp semantics")
        if minute_publication_lag < timedelta(0):
            raise ValueError("minute_publication_lag cannot be negative")
        self._client_override = client
        self._clock = clock
        self.minute_timestamp_semantics = minute_timestamp_semantics
        self.minute_publication_lag = minute_publication_lag
        self.minute_volume_unit = minute_volume_unit

    @property
    def client(self) -> ModuleType | object:
        if self._client_override is not None:
            return self._client_override
        try:
            return importlib.import_module("akshare")
        except ModuleNotFoundError as exc:
            raise MissingAKShareDependency(
                "AKShare is optional; install the project's research extra before live ingestion"
            ) from exc

    def _fetched_at(self) -> datetime:
        return _aware_shanghai(self._clock())

    def _call(self, endpoint: str, **params: object) -> pd.DataFrame:
        try:
            response = getattr(self.client, endpoint)(**params)
        except Exception as exc:
            raise AKShareDataError(
                f"AKShare endpoint {endpoint} failed with {type(exc).__name__}"
            ) from exc
        return _require_frame(response, endpoint=endpoint)

    @staticmethod
    def _batch(
        *,
        raw: pd.DataFrame,
        normalized: pd.DataFrame,
        dataset: str,
        endpoint: str,
        params: dict[str, object],
        fetched_at: datetime,
        schema_version: str,
        units: dict[str, str] | None = None,
        availability_policy: str,
    ) -> DataBatch:
        source_timestamp: datetime | None = None
        for field in ("source_timestamp", "timestamp", "available_at"):
            if field in normalized and normalized[field].notna().any():
                source_timestamp = (
                    normalized.loc[normalized[field].notna(), field]
                    .max()
                    .to_pydatetime()
                )
                break
        if source_timestamp is None:
            source_timestamp = fetched_at
        audit = DataAudit(
            dataset=dataset,
            source="akshare",
            endpoint=endpoint,
            params=params,
            source_timestamp=source_timestamp,
            fetched_at=fetched_at,
            schema_version=schema_version,
            units=units or {},
            availability_policy=availability_policy,
        )
        batch = DataBatch(
            raw=raw.copy(), normalized=normalized.reset_index(drop=True), audit=audit
        )
        batch.validate()
        return batch

    def fetch_trading_calendar(self) -> DataBatch:
        endpoint = "tool_trade_date_hist_sina"
        fetched_at = self._fetched_at()
        raw = self._call(endpoint)
        date_col = _column(raw, "trade_date", "交易日", "日期")
        normalized = pd.DataFrame(
            {"trade_date": pd.to_datetime(raw[date_col], errors="coerce").dt.date}
        )
        if normalized["trade_date"].isna().any():
            raise AKShareDataError("trading calendar contains invalid dates")
        normalized = normalized.drop_duplicates().sort_values("trade_date")
        normalized["source"] = self.source
        normalized["source_timestamp"] = fetched_at
        normalized["available_at"] = fetched_at
        normalized["fetched_at"] = fetched_at
        normalized["schema_version"] = "X_TRADING_CALENDAR_V0.1"
        return self._batch(
            raw=raw,
            normalized=normalized,
            dataset="trading_calendar",
            endpoint=endpoint,
            params={},
            fetched_at=fetched_at,
            schema_version="X_TRADING_CALENDAR_V0.1",
            availability_policy="calendar_response_observed_at_fetch",
        )

    def fetch_current_security_master(self) -> DataBatch:
        """Capture a current-only security-master slice.

        AKShare's code/name endpoint is not treated as historical evidence. Its
        effective and availability timestamps start at this capture, preventing
        a current name or risk label from being backfilled into earlier dates.
        """

        endpoint = "stock_info_a_code_name"
        fetched_at = self._fetched_at()
        raw = self._call(endpoint)
        symbol_col = _column(raw, "code", "代码", "symbol")
        name_col = _column(raw, "name", "名称", "证券简称")
        symbols = raw[symbol_col].map(normalize_symbol)
        names = raw[name_col].astype("string").str.strip()
        normalized = pd.DataFrame({"symbol": symbols, "name": names})
        normalized["exchange"] = normalized["symbol"].map(_exchange)
        normalized["board"] = normalized["symbol"].map(classify_board)
        normalized["status"] = "LISTED"
        normalized["is_st"] = (
            names.str.upper().str.replace(" ", "", regex=False).str.contains("ST")
        )
        normalized["is_suspended"] = pd.NA
        normalized["listed_on"] = pd.NaT
        normalized["delisted_on"] = pd.NaT
        normalized["effective_from"] = fetched_at
        normalized["effective_to"] = pd.NaT
        normalized["available_at"] = fetched_at
        normalized["source"] = self.source
        normalized["source_timestamp"] = fetched_at
        normalized["fetched_at"] = fetched_at
        normalized["schema_version"] = "X_SECURITY_MASTER_V0.1"
        duplicates = normalized["symbol"].duplicated(keep=False)
        if duplicates.any():
            symbols_with_duplicates = sorted(
                normalized.loc[duplicates, "symbol"].unique()
            )
            raise AKShareDataError(
                f"current security master contains duplicate symbols: {symbols_with_duplicates}"
            )
        normalized = normalized.sort_values("symbol")
        return self._batch(
            raw=raw,
            normalized=normalized,
            dataset="security_master",
            endpoint=endpoint,
            params={"scope": "current_only"},
            fetched_at=fetched_at,
            schema_version="X_SECURITY_MASTER_V0.1",
            availability_policy="current_snapshot_valid_from_fetch_only",
        )

    def fetch_daily_bars(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        adjust: str = "",
    ) -> DataBatch:
        if adjust not in {"", "qfq", "hfq"}:
            raise ValueError("adjust must be one of '', 'qfq', or 'hfq'")
        code = normalize_symbol(symbol)
        endpoint = "stock_zh_a_hist"
        params = {
            "symbol": code,
            "period": "daily",
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust,
        }
        fetched_at = self._fetched_at()
        raw = self._call(endpoint, **params)
        date_col = _column(raw, "日期", "date")
        field_map = {
            "open": ("开盘", "open"),
            "high": ("最高", "high"),
            "low": ("最低", "low"),
            "close": ("收盘", "close"),
            "volume": ("成交量", "volume"),
            "turnover": ("成交额", "amount", "turnover"),
        }
        normalized = pd.DataFrame(
            {"trade_date": pd.to_datetime(raw[date_col], errors="coerce")}
        )
        for target, candidates in field_map.items():
            col = _column(raw, *candidates)
            normalized[target] = pd.to_numeric(raw[col], errors="coerce")
        if normalized.isna().any().any():
            raise AKShareDataError("daily bars contain invalid required values")
        _validate_bars(normalized, dataset="daily bars")
        if normalized["trade_date"].duplicated().any():
            raise AKShareDataError("daily bars contain duplicate trade dates")
        normalized["symbol"] = code
        normalized["adjustment"] = adjust or "none"
        normalized["available_at"] = normalized["trade_date"].map(
            lambda value: datetime.combine(
                (value + timedelta(days=1)).date(), datetime.min.time(), tzinfo=SHANGHAI
            )
        )
        normalized["source"] = self.source
        normalized["source_timestamp"] = normalized["trade_date"].map(
            lambda value: datetime.combine(value.date(), time(15, 0), tzinfo=SHANGHAI)
        )
        normalized["fetched_at"] = fetched_at
        normalized["schema_version"] = "X_DAILY_BAR_V0.1"
        normalized = normalized.sort_values("trade_date")
        return self._batch(
            raw=raw,
            normalized=normalized,
            dataset="daily_bars",
            endpoint=endpoint,
            params=params,
            fetched_at=fetched_at,
            schema_version="X_DAILY_BAR_V0.1",
            units={
                "volume": "provider_native_unverified",
                "turnover": "CNY_unverified",
            },
            availability_policy="daily_bar_conservative_next_midnight",
        )

    def fetch_minute_bars(
        self,
        symbol: str,
        *,
        start: str,
        end: str,
        period: str = "1",
        adjust: str = "",
    ) -> DataBatch:
        if period not in {"1", "5", "15", "30", "60"}:
            raise ValueError("unsupported minute period")
        if adjust not in {"", "qfq", "hfq"}:
            raise ValueError("adjust must be one of '', 'qfq', or 'hfq'")
        code = normalize_symbol(symbol)
        endpoint = "stock_zh_a_hist_min_em"
        params = {
            "symbol": code,
            "start_date": start,
            "end_date": end,
            "period": period,
            "adjust": adjust,
        }
        fetched_at = self._fetched_at()
        raw = self._call(endpoint, **params)
        time_col = _column(raw, "时间", "日期", "datetime", "timestamp")
        fields = {
            "open": ("开盘", "open"),
            "high": ("最高", "high"),
            "low": ("最低", "low"),
            "close": ("收盘", "close"),
            "volume": ("成交量", "volume"),
            "turnover": ("成交额", "amount", "turnover"),
        }
        normalized = pd.DataFrame({"timestamp": _local_timestamps(raw[time_col])})
        for target, candidates in fields.items():
            col = _column(raw, *candidates)
            normalized[target] = pd.to_numeric(raw[col], errors="coerce")
        if (
            normalized[["open", "high", "low", "close", "volume", "turnover"]]
            .isna()
            .any()
            .any()
        ):
            raise AKShareDataError("minute bars contain invalid required values")
        _validate_bars(normalized, dataset="minute bars")
        avg_col = _column(raw, "均价", "average_price", "vwap", required=False)
        normalized["vwap"] = (
            pd.to_numeric(raw[avg_col], errors="coerce") if avg_col else pd.NA
        )
        normalized["symbol"] = code
        normalized["adjustment"] = adjust or "none"
        normalized["volume_unit"] = self.minute_volume_unit
        normalized["turnover_unit"] = "CNY_unverified"
        if self.minute_timestamp_semantics == "bar_end":
            normalized["available_at"] = (
                normalized["timestamp"] + self.minute_publication_lag
            )
        elif self.minute_timestamp_semantics == "bar_start":
            normalized["available_at"] = (
                normalized["timestamp"]
                + timedelta(minutes=int(period))
                + self.minute_publication_lag
            )
        else:
            normalized["available_at"] = pd.NaT
        normalized["availability_verified"] = (
            self.minute_timestamp_semantics != "unverified"
        )
        normalized["source"] = self.source
        normalized["source_timestamp"] = normalized["timestamp"]
        normalized["fetched_at"] = fetched_at
        normalized["schema_version"] = "X_MINUTE_BAR_V0.1"
        if normalized["timestamp"].duplicated().any():
            raise AKShareDataError("minute bars contain duplicate timestamps")
        normalized = normalized.sort_values("timestamp")
        return self._batch(
            raw=raw,
            normalized=normalized,
            dataset="minute_bars",
            endpoint=endpoint,
            params={
                **params,
                "timestamp_semantics": self.minute_timestamp_semantics,
                "publication_lag_seconds": self.minute_publication_lag.total_seconds(),
            },
            fetched_at=fetched_at,
            schema_version="X_MINUTE_BAR_V0.1",
            units={"volume": self.minute_volume_unit, "turnover": "CNY_unverified"},
            availability_policy=f"minute_timestamp_{self.minute_timestamp_semantics}",
        )
