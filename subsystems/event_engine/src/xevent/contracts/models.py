"""Phase 1 注册、证据和事件的数据契约；不执行状态转换或分析。"""
from typing import Literal

from pydantic import Field, model_validator

from .common import (
    Band, ClaimKind, Contract, Count, DerivedEnvelope, Items, ObservationWindow,
    Ratio, SampleStatistic, SHA256, Text, UTCDateTime, VersionEnvelope, VersionRef,
)

FactState = Literal[
    "UNVERIFIED", "PLAUSIBLE", "PARTIALLY_CONFIRMED", "INDEPENDENTLY_CONFIRMED",
    "OFFICIALLY_CONFIRMED", "IMPLEMENTED", "CONTRADICTED", "INVALIDATED",
]
NarrativeState = Literal[
    "UNKNOWN", "SILENT", "EXPERT_DISCOVERY", "EARLY_DIFFUSION", "RAPID_DIFFUSION",
    "MAINSTREAM", "CROWDED", "DECAYING",
]
PricingState = Literal[
    "UNKNOWN", "NO_REACTION", "INITIAL_REACTION", "PARTIAL_REPRICING",
    "SECTOR_DIFFUSION", "FULLY_PRICED", "OVERTRADED",
]
# 这里只声明冻结词表，不实现后续Phase的映射/评级业务。
MappingState = Literal[
    "VERIFIED_DIRECT", "VERIFIED_INDIRECT", "PLAUSIBLE", "NARRATIVE_ONLY",
    "MIXED", "CONTRADICTED", "INVALID",
]
Grade = Literal["ALPHA1", "ALPHA2", "BETA", "WATCH", "OVERPRICED", "REJECT"]
ImpactDirection = Literal["POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"]
StatementType = Literal[
    "LEGAL_DOCUMENT", "POLICY_NOTICE", "PRESS_CONFERENCE", "SPEECH", "HEARING",
    "INTERVIEW", "INFORMAL_QA", "SOCIAL_ORIGINAL", "REPOST", "LIKE",
    "ANONYMOUS_REPORT", "UNKNOWN", "OTHER",
]
EvidenceType = Literal[
    "OFFICIAL_DOCUMENT", "COMPANY_DISCLOSURE", "NEWS_REPORT", "SOCIAL_POST",
    "TRANSCRIPT", "UNKNOWN", "OTHER",
]
EventType = Literal[
    "POLICY", "CORPORATE", "SUPPLY_DEMAND", "MACRO", "GEOPOLITICAL",
    "TECHNOLOGY", "UNKNOWN", "OTHER",
]


def identity_matches(record, field):
    if getattr(record, field) != record.object_id:
        raise ValueError(f"IDENTITY_MISMATCH：{field}必须等于公共信封object_id")


def require_input_refs(record, refs):
    known = {(r.object_id, r.version) for r in record.input_version_refs}
    if any((r.object_id, r.version) not in known for r in refs):
        raise ValueError("PIT_REFERENCE：关键引用必须同时声明具体输入版本及其可用时间")


def external_raw(kind, raw_type, missing_reason):
    if kind == "OTHER" and not raw_type:
        raise ValueError("EXTERNAL_RAW：OTHER必须保存原始raw_type")
    if kind == "UNKNOWN" and raw_type is None and not missing_reason:
        raise ValueError("EXTERNAL_UNKNOWN：来源未提供类别时必须说明原因")


def statistics_cutoff(record):
    return record.research_computed_at if record.public_pit else record.computed_at


class Source(VersionEnvelope):
    source_id: Text
    name_zh: Text = Field(description="来源中文名称")
    platform: Text
    canonical_locator: Text
    identity_status: Literal["VERIFIED", "UNVERIFIED", "DISPUTED"] = "UNVERIFIED"
    tier: Literal["S0", "S1", "S2", "S3", "S4"]
    roles: Items[Literal["FACT", "POLICY_INTENT", "EXPLANATION", "NARRATIVE", "DIFFUSION"]]
    access_method: Text
    retention_policy: Text
    enabled: bool = False
    terms_status: Literal["UNKNOWN", "REVIEWED", "UNAVAILABLE"] = "UNKNOWN"
    authorization_status: Literal["UNKNOWN", "AUTHORIZED", "NOT_REQUIRED", "DENIED"] = "UNKNOWN"
    allowed_uses: Items[Text] | None = Field(default=None, description="null=未知，[]无已允许用途；公开访问不等于授权")
    raw_retention_allowed: bool | None = Field(default=None, description="null=UNKNOWN；不推定可以永久留存")
    access_restrictions: Items[Text] | None = None

    @model_validator(mode="after")
    def identity(self):
        identity_matches(self, "source_id")
        return self


class SourceTopicProfile(DerivedEnvelope):
    source_id: Text
    source_ref: VersionRef
    topic_id: Text
    reliability_band: Band = "UNKNOWN"
    expertise_band: Band = "UNKNOWN"
    influence_band: Band = "UNKNOWN"
    diffusion_band: Band = "UNKNOWN"
    lead_time_stats: SampleStatistic | None = None
    missing_reason: Text | None = "UNKNOWN"

    @model_validator(mode="after")
    def profile_gate(self):
        if self.source_id != self.source_ref.object_id:
            raise ValueError("IDENTITY_MISMATCH：source_ref不匹配")
        require_input_refs(self, (self.source_ref, *self.evidence_refs))
        if self.lead_time_stats and self.lead_time_stats.outcome_available_at > statistics_cutoff(self):
            raise ValueError("PIT_STATS：统计不能使用计算完成后才可知的结果")
        return self


class NarrativeSourceProfile(SourceTopicProfile):
    category: Literal["INDUSTRY_LEADER", "EXPLAINER", "ATTENTION_MOVER", "FOLLOWER", "NOISE", "UNKNOWN"]
    followers: Count | None = Field(default=None, description="粉丝数不等于事实可信度，不自动改变reliability_band")
    originality: Ratio | None = None
    citation_rate: Ratio | None = None
    leading_stats: SampleStatistic | None = None
    following_stats: SampleStatistic | None = None
    posthoc_stats: SampleStatistic | None = None
    edit_stats: SampleStatistic | None = None
    delete_stats: SampleStatistic | None = None
    sample_n: Count
    observation_window: ObservationWindow

    @model_validator(mode="after")
    def statistics_gate(self):
        if self.observation_window.end > statistics_cutoff(self):
            raise ValueError("PIT_WINDOW：不能统计计算完成后才结束的观察窗")
        stats = (self.leading_stats, self.following_stats, self.posthoc_stats, self.edit_stats, self.delete_stats)
        for stat in stats:
            if stat is not None:
                if stat.outcome_available_at > statistics_cutoff(self):
                    raise ValueError("PIT_STATS：未来结果不得回填过去画像")
                if stat.denominator > self.sample_n:
                    raise ValueError("STAT_COUNT：指标分母不得超过画像样本数")
        if any(v is None for v in (self.followers, self.originality, self.citation_rate, *stats)) and not self.missing_reason:
            raise ValueError("STAT_UNKNOWN：未知指标保留null并说明原因")
        return self


class Actor(VersionEnvelope):
    actor_id: Text
    name_zh: Text
    entity_type: Literal["PERSON", "INSTITUTION"]
    organization_ref: VersionRef | None = None
    role_title_zh: Text | None = None
    term_effective_from: UTCDateTime | None = None
    term_effective_to: UTCDateTime | None = None
    verified_accounts: Items[VersionRef] = ()

    @model_validator(mode="after")
    def actor_gate(self):
        identity_matches(self, "actor_id")
        if self.term_effective_to is not None and (self.term_effective_from is None or self.term_effective_to <= self.term_effective_from):
            raise ValueError("ACTOR_TERM：职位有效区间必须左闭右开")
        if self.role_title_zh is not None and self.term_effective_from is None:
            raise ValueError("ACTOR_TERM：职位必须声明生效时间")
        if self.term_effective_from != self.effective_from or self.term_effective_to != self.effective_to:
            raise ValueError("ACTOR_TERM：职位版本有效区间必须与公共信封一致")
        refs = (*self.verified_accounts, *self.evidence_refs)
        if self.organization_ref:
            refs = (*refs, self.organization_ref)
        require_input_refs(self, refs)
        return self


class ActorTopicProfile(DerivedEnvelope):
    actor_id: Text
    actor_ref: VersionRef
    topic_id: Text
    policy_authority: Band = "UNKNOWN"
    corporate_authority: Band = "UNKNOWN"
    expertise_band: Band = "UNKNOWN"
    influence_band: Band = "UNKNOWN"
    statement_count: Count
    realized_count: Count
    partial_count: Count
    denied_count: Count
    unresolved_count: Count
    outcome_available_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def actor_topic_gate(self):
        if self.actor_id != self.actor_ref.object_id:
            raise ValueError("IDENTITY_MISMATCH：actor_ref不匹配")
        require_input_refs(self, (self.actor_ref, *self.evidence_refs))
        resolved = self.realized_count + self.partial_count + self.denied_count
        if resolved + self.unresolved_count != self.statement_count:
            raise ValueError("STAT_COUNT：结果分类合计必须等于发言样本数")
        if resolved and self.outcome_available_at is None:
            raise ValueError("PIT_STATS：已兑现/否定统计必须声明结果可知时间")
        if self.outcome_available_at and self.outcome_available_at > statistics_cutoff(self):
            raise ValueError("PIT_STATS：未来兑现结果不得回填过去")
        return self


class Statement(DerivedEnvelope):
    actor_id: Text | None = None
    actor_ref: VersionRef | None = None
    source_id: Text
    source_ref: VersionRef
    topic_id: Text
    statement_type: StatementType
    raw_type: Text | None = None
    classification_missing_reason: Text | None = None
    claim_kind: ClaimKind
    policy_certainty: Literal["LOW", "MEDIUM", "HIGH", "IMPLEMENTED", "UNKNOWN"] = "UNKNOWN"
    market_shock_potential: Band = "UNKNOWN"
    evidence_ref: VersionRef

    @model_validator(mode="after")
    def statement_gate(self):
        external_raw(self.statement_type, self.raw_type, self.classification_missing_reason)
        if self.source_id != self.source_ref.object_id:
            raise ValueError("IDENTITY_MISMATCH：来源引用不匹配")
        if self.actor_id != (self.actor_ref.object_id if self.actor_ref else None):
            raise ValueError("IDENTITY_MISMATCH：人物引用不匹配")
        refs = (self.source_ref, self.evidence_ref)
        require_input_refs(self, (*refs, self.actor_ref) if self.actor_ref else refs)
        return self


class EvidenceVersion(VersionEnvelope):
    evidence_id: Text
    source_id: Text
    source_ref: VersionRef
    canonical_url_or_locator: Text
    original_language: Text
    raw_object_ref: Text
    raw_content_hash: SHA256
    first_seen_text_ref: Text
    origin_cluster_id: Text
    is_first_hand: bool | None = Field(description="null表示未查明；不是默认一手")
    independence_status: Literal["INDEPENDENT", "SAME_ORIGIN", "UNKNOWN"]
    claim_kind: ClaimKind
    published_at: UTCDateTime | None
    public_available_at: UTCDateTime | None
    first_seen_at: UTCDateTime
    collected_at: UTCDateTime
    ready_at: UTCDateTime = Field(description="解析、规范化与必需校验完成时间，不是提交完成时间")
    evidence_type: EvidenceType
    raw_type: Text | None = None
    classification_missing_reason: Text | None = None
    quality_status: Literal["VALIDATED", "PARTIAL", "UNVERIFIED", "REJECTED"]

    @model_validator(mode="after")
    def evidence_gate(self):
        identity_matches(self, "evidence_id")
        external_raw(self.evidence_type, self.raw_type, self.classification_missing_reason)
        if self.source_id != self.source_ref.object_id:
            raise ValueError("IDENTITY_MISMATCH：来源引用不匹配")
        require_input_refs(self, (self.source_ref,))
        if self.available_at < max(self.first_seen_at, self.collected_at, self.ready_at, self.recorded_at):
            raise ValueError("PIT_EVIDENCE：可用时间必须覆盖首次观测、接收、ready与耐久化提交")
        if not self.first_seen_at <= self.collected_at <= self.ready_at <= self.recorded_at:
            raise ValueError("EVIDENCE_ORDER：接收、校验、提交时间顺序错误")
        if self.quality_status in ("UNVERIFIED", "REJECTED") and self.status in ("READY", "DEGRADED"):
            raise ValueError("EVIDENCE_NOT_READY：尚未校验或校验失败不能发布正式Evidence")
        if self.public_pit and self.public_available_at != self.public_pit.public_available_at:
            raise ValueError("PIT_PUBLIC_TIME：公开证据时间与模拟证明不一致")
        return self


class EvidenceRelation(DerivedEnvelope):
    subject_ref: VersionRef
    evidence_ref: VersionRef
    relation: Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"]
    quoted_span: Text
    interpretation_zh: Text

    @model_validator(mode="after")
    def references(self):
        require_input_refs(self, (self.subject_ref, self.evidence_ref))
        return self


class EntityRef(Contract):
    entity_id: Text
    entity_type: Literal["PERSON", "INSTITUTION", "OBJECT", "REGION", "UNRESOLVED"]
    name_zh: Text


class EventDNA(Contract):
    actor_refs: Items[VersionRef]
    action_code: Text
    object_entities: Items[EntityRef] = Field(min_length=1, description="经济/政策等事件客体；不是股票或概念标签")
    target_entities: Items[EntityRef] = ()
    domain_ids: Items[Text]
    geographic_scope: Items[Text]
    temporal_scope: Text
    identity_rule_version: Text


class EventVersion(DerivedEnvelope):
    event_id: Text
    title_zh: Text
    event_type: EventType
    raw_type: Text | None = None
    classification_missing_reason: Text | None = None
    dna: EventDNA
    first_public_at: UTCDateTime | None
    first_seen_at: UTCDateTime
    last_material_update_at: UTCDateTime
    fact_state: FactState = "UNVERIFIED"
    narrative_state: NarrativeState = "UNKNOWN"
    pricing_state: PricingState = "UNKNOWN"
    priority: Literal["P0", "P1", "P2", "P3"] = "P3"
    lifecycle_status: Literal["ACTIVE", "ARCHIVED"] = "ACTIVE"
    event_cluster_ids: Items[Text] = ()
    hypothesis_set_ref: VersionRef | None = None
    revision_reason: Text

    @model_validator(mode="after")
    def event_gate(self):
        identity_matches(self, "event_id")
        external_raw(self.event_type, self.raw_type, self.classification_missing_reason)
        if not self.evidence_refs:
            raise ValueError("EVENT_EVIDENCE：事件必须引用具体证据版本")
        if self.last_material_update_at < self.first_seen_at or self.computed_at < self.last_material_update_at:
            raise ValueError("PIT_EVENT：事件更新时间必须介于发现和计算完成之间")
        refs = (*self.evidence_refs, *self.dna.actor_refs)
        require_input_refs(self, (*refs, self.hypothesis_set_ref) if self.hypothesis_set_ref else refs)
        return self
