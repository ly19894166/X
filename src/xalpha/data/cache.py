from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from .base import DataAudit, DataBatch

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._=-]+$")


class CacheIntegrityError(RuntimeError):
    """Stored bytes no longer match their recorded digest."""


class CacheCollisionError(RuntimeError):
    """An immutable cache partition already exists with different content."""


@dataclass(frozen=True)
class CacheEntry:
    directory: Path
    raw_path: Path
    normalized_path: Path
    audit_path: Path
    raw_sha256: str
    normalized_sha256: str


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _frame_bytes(frame: pd.DataFrame) -> bytes:
    payload = frame.to_json(
        orient="table",
        date_format="iso",
        date_unit="us",
        index=False,
        force_ascii=False,
    )
    return (payload + "\n").encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=path.parent) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _audit_to_dict(audit: DataAudit) -> dict[str, Any]:
    return _jsonable(asdict(audit))


def _audit_from_dict(payload: dict[str, Any]) -> DataAudit:
    return DataAudit(
        dataset=payload["dataset"],
        source=payload["source"],
        endpoint=payload["endpoint"],
        params=payload.get("params", {}),
        source_timestamp=(
            datetime.fromisoformat(payload["source_timestamp"])
            if payload.get("source_timestamp")
            else None
        ),
        fetched_at=datetime.fromisoformat(payload["fetched_at"]),
        schema_version=payload["schema_version"],
        units=payload.get("units", {}),
        availability_policy=payload.get("availability_policy", "unverified"),
    )


class AuditedLocalCache:
    """Append-only raw/normalized cache with content verification.

    Every partition contains the provider payload, its normalized equivalent,
    and an audit manifest binding both files to SHA-256 digests. Existing
    partitions are never silently overwritten.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    @staticmethod
    def _component(value: str, *, field: str) -> str:
        text = str(value)
        if text in {".", ".."} or not _SAFE_COMPONENT.fullmatch(text):
            raise ValueError(f"unsafe cache {field}: {value!r}")
        return text

    def _directory_for(self, *, source: str, dataset: str, partition: str) -> Path:
        source = self._component(source, field="source")
        dataset = self._component(dataset, field="dataset")
        part = self._component(partition, field="partition")
        directory = (self.root / source / dataset / part).resolve()
        if self.root not in directory.parents:
            raise ValueError("cache partition escapes cache root")
        return directory

    def _directory(self, audit: DataAudit, partition: str) -> Path:
        return self._directory_for(
            source=audit.source, dataset=audit.dataset, partition=partition
        )

    @staticmethod
    def _entry(directory: Path, manifest: dict[str, Any]) -> CacheEntry:
        raw_name = manifest.get("files", {}).get("raw", {}).get("name")
        normalized_name = manifest.get("files", {}).get("normalized", {}).get("name")
        if raw_name != "raw.table.json" or normalized_name != "normalized.table.json":
            raise CacheIntegrityError(
                "cache manifest contains unexpected payload paths"
            )
        return CacheEntry(
            directory=directory,
            raw_path=directory / raw_name,
            normalized_path=directory / normalized_name,
            audit_path=directory / "audit.json",
            raw_sha256=manifest["files"]["raw"]["sha256"],
            normalized_sha256=manifest["files"]["normalized"]["sha256"],
        )

    def store(self, batch: DataBatch, *, partition: str) -> CacheEntry:
        batch.validate()
        directory = self._directory(batch.audit, partition)
        raw_payload = _frame_bytes(batch.raw)
        normalized_payload = _frame_bytes(batch.normalized)
        manifest = {
            "format_version": "X_AUDITED_CACHE_V0.1",
            "immutable": True,
            "audit": _audit_to_dict(batch.audit),
            "row_counts": {
                "raw": len(batch.raw),
                "normalized": len(batch.normalized),
            },
            "files": {
                "raw": {"name": "raw.table.json", "sha256": _sha256(raw_payload)},
                "normalized": {
                    "name": "normalized.table.json",
                    "sha256": _sha256(normalized_payload),
                },
            },
        }
        audit_payload = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        audit_path = directory / "audit.json"

        if audit_path.exists():
            existing = json.loads(audit_path.read_text(encoding="utf-8"))
            if existing != manifest:
                raise CacheCollisionError(
                    f"immutable cache partition already contains different data: {directory}"
                )
            return self.verify(batch.audit, partition=partition)

        directory.mkdir(parents=True, exist_ok=True)
        _atomic_write(directory / "raw.table.json", raw_payload)
        _atomic_write(directory / "normalized.table.json", normalized_payload)
        _atomic_write(audit_path, audit_payload)
        return self.verify(batch.audit, partition=partition)

    def verify(self, audit: DataAudit, *, partition: str) -> CacheEntry:
        directory = self._directory(audit, partition)
        entry, _ = self._verify_directory(directory, expected_audit=audit)
        return entry

    def _verify_directory(
        self, directory: Path, *, expected_audit: DataAudit | None = None
    ) -> tuple[CacheEntry, dict[str, Any]]:
        audit_path = directory / "audit.json"
        if not audit_path.is_file():
            raise FileNotFoundError(audit_path)
        try:
            manifest = json.loads(audit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CacheIntegrityError("cache audit manifest is unreadable") from exc
        if manifest.get("format_version") != "X_AUDITED_CACHE_V0.1":
            raise CacheIntegrityError("unsupported cache audit format")
        if expected_audit is not None and manifest.get("audit") != _audit_to_dict(
            expected_audit
        ):
            raise CacheIntegrityError(
                "cache audit metadata does not match requested batch"
            )
        entry = self._entry(directory, manifest)
        for path, expected in (
            (entry.raw_path, entry.raw_sha256),
            (entry.normalized_path, entry.normalized_sha256),
        ):
            if not path.is_file():
                raise CacheIntegrityError(f"cache payload is missing: {path.name}")
            actual = _sha256(path.read_bytes())
            if actual != expected:
                raise CacheIntegrityError(
                    f"cache digest mismatch for {path.name}: {actual} != {expected}"
                )
        return entry, manifest

    @staticmethod
    def _load_verified(entry: CacheEntry, manifest: dict[str, Any]) -> DataBatch:
        stored_audit = _audit_from_dict(manifest["audit"])
        raw = pd.read_json(
            StringIO(entry.raw_path.read_text(encoding="utf-8")), orient="table"
        )
        normalized = pd.read_json(
            StringIO(entry.normalized_path.read_text(encoding="utf-8")), orient="table"
        )
        expected_counts = manifest.get("row_counts", {})
        if len(raw) != expected_counts.get("raw") or len(
            normalized
        ) != expected_counts.get("normalized"):
            raise CacheIntegrityError("cache row counts do not match audit manifest")
        batch = DataBatch(raw=raw, normalized=normalized, audit=stored_audit)
        batch.validate()
        return batch

    def load(self, audit: DataAudit, *, partition: str) -> DataBatch:
        directory = self._directory(audit, partition)
        entry, manifest = self._verify_directory(directory, expected_audit=audit)
        return self._load_verified(entry, manifest)

    def load_partition(self, *, source: str, dataset: str, partition: str) -> DataBatch:
        """Load and verify a partition after a process restart."""

        directory = self._directory_for(
            source=source, dataset=dataset, partition=partition
        )
        entry, manifest = self._verify_directory(directory)
        return self._load_verified(entry, manifest)
