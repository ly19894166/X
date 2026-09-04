from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from .universe import normalize_symbol

SHANGHAI = ZoneInfo("Asia/Shanghai")
SECURITY_MASTER_SCHEMA_VERSION = "X_SECURITY_MASTER_V0.1"
SECURITY_MASTER_COLUMNS = (
    "symbol",
    "name",
    "exchange",
    "board",
    "status",
    "is_st",
    "is_suspended",
    "listed_on",
    "delisted_on",
    "effective_from",
    "effective_to",
    "available_at",
    "source",
    "source_timestamp",
    "fetched_at",
    "schema_version",
)


class SecurityMasterContractError(ValueError):
    pass


def _as_shanghai(
    value: str | date | datetime | pd.Timestamp, *, end_of_day: bool = False
) -> pd.Timestamp:
    if isinstance(value, date) and not isinstance(value, datetime):
        clock = time.max if end_of_day else time.min
        stamp = pd.Timestamp(datetime.combine(value, clock))
    else:
        stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise SecurityMasterContractError("invalid point-in-time timestamp")
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(SHANGHAI)
    else:
        stamp = stamp.tz_convert(SHANGHAI)
    return stamp


def _coerce_timestamp_column(frame: pd.DataFrame, field: str) -> pd.Series:
    values: list[pd.Timestamp | pd.NaT] = []
    for value in frame[field]:
        if pd.isna(value):
            values.append(pd.NaT)
        else:
            values.append(_as_shanghai(value))
    return pd.Series(values, index=frame.index, dtype="datetime64[ns, Asia/Shanghai]")


class PointInTimeSecurityMaster:
    """Bitemporal security-master base for historical universe reconstruction.

    ``effective_*`` says when a record describes the security. ``available_at``
    says when that record was provably knowable. Both gates must pass before a
    record can enter a historical decision snapshot.
    """

    def __init__(self, records: pd.DataFrame):
        missing = set(SECURITY_MASTER_COLUMNS).difference(records.columns)
        if missing:
            raise SecurityMasterContractError(
                f"security master missing columns: {sorted(missing)}"
            )
        frame = records.loc[:, SECURITY_MASTER_COLUMNS].copy()
        frame["symbol"] = frame["symbol"].map(normalize_symbol)
        for field in (
            "listed_on",
            "delisted_on",
            "effective_from",
            "effective_to",
            "available_at",
            "source_timestamp",
            "fetched_at",
        ):
            frame[field] = _coerce_timestamp_column(frame, field)

        if frame["effective_from"].isna().any():
            raise SecurityMasterContractError("effective_from is required")
        if frame["available_at"].isna().any():
            raise SecurityMasterContractError("available_at is required")
        if frame["source_timestamp"].isna().any() or frame["fetched_at"].isna().any():
            raise SecurityMasterContractError(
                "source_timestamp and fetched_at are required"
            )
        if (frame["schema_version"] != SECURITY_MASTER_SCHEMA_VERSION).any():
            raise SecurityMasterContractError(
                "unsupported security-master schema version"
            )
        invalid_interval = frame["effective_to"].notna() & (
            frame["effective_to"] <= frame["effective_from"]
        )
        if invalid_interval.any():
            raise SecurityMasterContractError(
                "effective intervals must be half-open and positive"
            )
        if (frame["source_timestamp"] > frame["fetched_at"]).any():
            raise SecurityMasterContractError(
                "source_timestamp cannot be later than fetched_at"
            )
        if (frame["available_at"] > frame["fetched_at"]).any():
            raise SecurityMasterContractError(
                "available_at cannot be later than fetched_at"
            )
        self._records = frame.sort_values(["symbol", "effective_from"]).reset_index(
            drop=True
        )
        self._assert_no_overlapping_effective_intervals()

    @property
    def records(self) -> pd.DataFrame:
        return self._records.copy()

    def _assert_no_overlapping_effective_intervals(self) -> None:
        for symbol, group in self._records.groupby("symbol", sort=False):
            previous_end: pd.Timestamp | None = None
            first = True
            for row in group.itertuples(index=False):
                if not first and (
                    previous_end is None or row.effective_from < previous_end
                ):
                    raise SecurityMasterContractError(
                        f"overlapping effective intervals for {symbol}"
                    )
                previous_end = None if pd.isna(row.effective_to) else row.effective_to
                first = False

    def as_of(
        self,
        effective_at: str | date | datetime | pd.Timestamp,
        *,
        knowledge_cutoff: str | date | datetime | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        effective = _as_shanghai(
            effective_at,
            end_of_day=isinstance(effective_at, date)
            and not isinstance(effective_at, datetime),
        )
        knowledge = _as_shanghai(
            effective if knowledge_cutoff is None else knowledge_cutoff
        )
        frame = self._records
        selected = frame[
            (frame["effective_from"] <= effective)
            & (frame["effective_to"].isna() | (effective < frame["effective_to"]))
            & (frame["available_at"] <= knowledge)
            & (frame["listed_on"].isna() | (frame["listed_on"] <= effective))
            & (frame["delisted_on"].isna() | (effective < frame["delisted_on"]))
        ].copy()
        duplicates = selected["symbol"].duplicated(keep=False)
        if duplicates.any():
            symbols = sorted(selected.loc[duplicates, "symbol"].unique())
            raise SecurityMasterContractError(
                f"multiple point-in-time records for symbols: {symbols}"
            )
        return selected.sort_values("symbol").reset_index(drop=True)

    def universe(
        self,
        effective_at: str | date | datetime | pd.Timestamp,
        *,
        knowledge_cutoff: str | date | datetime | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Return all active securities, including ST and suspended rows.

        Execution eligibility is a later field on the decision snapshot; it is
        intentionally not used to shrink the research universe here.
        """

        frame = self.as_of(effective_at, knowledge_cutoff=knowledge_cutoff)
        return frame[frame["status"].isin({"LISTED", "SUSPENDED"})].reset_index(
            drop=True
        )
