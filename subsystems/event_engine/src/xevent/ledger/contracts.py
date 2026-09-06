"""Phase 2 领域契约；继续使用 Phase 1 时间、版本和严格类型。"""
from typing import Literal
import json

from pydantic import Field, model_validator

from ..contracts.common import ClaimKind, Contract, DerivedEnvelope, Items, Text, UTCDateTime, VersionEnvelope, VersionRef
from ..contracts.models import EventDNA


class RawObservation(Contract):
    source_ref: VersionRef
    locator: Text
    raw: bytes
    first_seen_at: UTCDateTime
    collected_at: UTCDateTime
    published_at: UTCDateTime | None = None
    content_version: Text
    change_type: Literal["INITIAL", "EDIT", "DELETE", "RETRACT"] = "INITIAL"
    origin_ref: VersionRef | None = None
    is_first_hand: bool | None = None
    claim_kind: ClaimKind = "NARRATIVE"
    # 仅来源明确结构化的字段；普通文本禁止猜测。值必须能在原文逐字定位。
    structured_fields: dict[Literal["amount", "effective_date", "legal_status", "detail", "retracted"], Text] = Field(default_factory=dict)
    structured_basis: Literal["SOURCE_STRUCTURED", "UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def order(self):
        if self.collected_at < self.first_seen_at:
            raise ValueError("PIT_OBSERVATION：接收完成不能早于首次看到")
        if self.structured_fields:
            try:
                value = json.loads(self.raw)
            except (ValueError, UnicodeError) as exc:
                raise ValueError("FIELD_PROOF：确定性结构规则只接受完整来源JSON对象") from exc
            if self.structured_basis != "SOURCE_STRUCTURED" or value != self.structured_fields:
                raise ValueError("FIELD_PROOF：结构字段必须完整对应原始JSON，不能遗漏正文")
        return self


class EventSeed(Contract):
    event_id: Text
    title_zh: Text
    dna: EventDNA


class EventLedgerEntry(DerivedEnvelope):
    event_ref: VersionRef
    previous_version: int | None = None
    operation: Literal["CREATE", "APPEND"]
    idempotency_key: Text


class EvidenceChange(DerivedEnvelope):
    evidence_ref: VersionRef
    prior_version_ref: VersionRef | None
    change_type: Literal["INITIAL", "EDIT", "DELETE", "RETRACT"]
    observed_at: UTCDateTime


class OriginClusterVersion(DerivedEnvelope):
    member_origin_ids: Items[Text]
    basis: Literal["FIRST_HAND", "EXACT_BYTES", "EXPLICIT_CHAIN", "CONFIRMED_SAME_ORIGIN", "UNRESOLVED"]
    verification: Literal["KNOWN_ORIGIN", "HOLD"]
    confirmation_ref: VersionRef | None = None
    proof_span: Text | None = None


class NoveltyDecision(DerivedEnvelope):
    classification: Literal["R0", "R1", "R2", "R3", "R4", "R5", "UNDETERMINED"]
    evidence_ref: VersionRef


class CollectorCursor(VersionEnvelope):
    source_id: Text
    cursor: Text | None = None
    since_id: Text | None = None
    etag: Text | None = None
    last_modified: Text | None = None
    last_success_at: UTCDateTime | None
    last_attempt_at: UTCDateTime
    last_received_at: UTCDateTime | None


class OutboxJob(DerivedEnvelope):
    event_ref: VersionRef
    job_status: Literal["PENDING", "DONE"]
    effect_key: Text
    result_zh: Text | None = None


class SourceHealth(VersionEnvelope):
    source_id: Text
    health: Literal["OK", "SOURCE_UNAVAILABLE", "AUTHORIZATION_HOLD"]
    last_attempt_at: UTCDateTime
    detail_zh: Text
