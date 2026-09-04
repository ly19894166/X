from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .base import DataBatch


class ReplayFixtureMissing(KeyError):
    pass


@dataclass(frozen=True)
class ReplayProvider:
    """Deterministic offline provider for pipeline and CI rehearsal.

    Fixtures are complete ``DataBatch`` objects, so replay preserves original
    provenance/availability metadata instead of inventing live timestamps.
    """

    fixtures: Mapping[str, DataBatch]
    source: str = "offline_replay"

    def get(self, key: str) -> DataBatch:
        if key not in self.fixtures:
            raise ReplayFixtureMissing(key)
        batch = self.fixtures[key]
        batch.validate()
        return DataBatch(
            raw=batch.raw.copy(deep=True),
            normalized=batch.normalized.copy(deep=True),
            audit=batch.audit,
        )

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.fixtures))
