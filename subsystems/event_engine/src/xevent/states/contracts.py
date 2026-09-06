"""Phase 3版本契约；PIT、不可变模型和JSON Schema复用Phase 1。"""
from typing import Literal, get_args

from pydantic import Field, model_validator

from ..contracts.common import (Contract, Count, DerivedEnvelope, Items, ObservationWindow,
                                PositiveInt, Text, UTCDateTime, VersionRef)
from ..contracts.models import FactState, require_input_refs

NarrativeState = Literal["UNKNOWN", "QUIET", "PROFESSIONAL_DISCOVERY", "EARLY_DIFFUSION",
                         "RAPID_DIFFUSION", "MAINSTREAM", "CROWDED", "DECAY"]
PricingState = Literal["UNKNOWN", "NO_REACTION", "INITIAL_REACTION", "LOCAL_REPRICING",
                       "SECTOR_DIFFUSION", "FULLY_PRICED", "OVERTRADED"]
Priority = Literal["P0", "P1", "P2", "P3"]
LifeBand = Literal["VERY_SHORT", "HOURLY", "OVERNIGHT", "ONE_TO_THREE_TRADING_DAYS",
                   "MEDIUM", "STRUCTURAL", "UNKNOWN"]
TriggerReason = Literal["NEW_PRIMARY_EVIDENCE", "OFFICIAL_CONFIRMATION", "OFFICIAL_DENIAL",
    "R3_MATERIAL_EVIDENCE", "R4_EVENT_MUTATION", "R5_COUNTEREVIDENCE", "NARRATIVE_ACCELERATION",
    "PRICE_STATE_CHANGE", "CROSS_ASSET_CONFIRMATION", "LINEAGE_CHANGE"]
AssessmentKind = Literal["PLAUSIBLE", "PARTIAL", "SUPPORT", "OFFICIAL_CONFIRMATION",
    "IMPLEMENTATION", "COUNTEREVIDENCE", "OFFICIAL_DENIAL", "INVALIDATION", "RESOLUTION"]


class Rules(Contract):
    window_seconds: PositiveInt = 3600
    rapid_min_sources: PositiveInt = 3
    mainstream_min_sources: PositiveInt = 5
    crowded_min_sources: PositiveInt = 10
    acceleration_factor: PositiveInt = 2
    cooldown_seconds: Count = 300
    life_band: LifeBand = "UNKNOWN"

    @model_validator(mode="after")
    def thresholds(self):
        if not self.rapid_min_sources <= self.mainstream_min_sources <= self.crowded_min_sources:
            raise ValueError("RULE_ORDER：传播阈值必须递增；仅离线工程初值，未校准")
        return self


class StatePolicy(DerivedEnvelope):
    rules: Rules


class EvidenceAssessment(DerivedEnvelope):
    event_ref: VersionRef
    evidence_ref: VersionRef
    kind: AssessmentKind
    quoted_span: Text
    reviewed_by: Text = Field(description="离线fixture或人工核验者；不是自动语义理解")
    interpretation_zh: Text
    authority_scope_zh: Text | None = Field(default=None, description="负责机构与本事件的权限依据；官方类别必填")
    event_started_at: UTCDateTime | None = Field(default=None, description="人工核验的实际事件开始时间；不拿发布时间代替")
    resolves_refs: Items[VersionRef] = ()

    @model_validator(mode="after")
    def gate(self):
        require_input_refs(self, (self.event_ref, self.evidence_ref, *self.resolves_refs))
        if self.kind in ("OFFICIAL_CONFIRMATION", "OFFICIAL_DENIAL") and not self.authority_scope_zh:
            raise ValueError("OFFICIAL_SCOPE：必须说明负责机构权限，S0标签本身不足")
        if self.event_started_at and self.event_started_at > self.computed_at:
            raise ValueError("PIT_STARTED：事件实际开始不能来自未来")
        return self


class SecurityPriceObservation(DerivedEnvelope):
    event_ref: VersionRef
    security_id: Text = Field(description="fixture标识，不执行证券身份/产业映射")
    observation_window: ObservationWindow
    observation: PricingState
    basis_zh: Text
    fixture_only: Literal[True] = True
    cross_asset_confirmed: bool = False

    @model_validator(mode="after")
    def gate(self):
        require_input_refs(self, (self.event_ref, *self.evidence_refs))
        if self.observation_window.end > self.computed_at:
            raise ValueError("PIT_PRICE：观察窗口尚未结束")
        if self.observation != "UNKNOWN" and not self.evidence_refs:
            raise ValueError("PRICE_PROOF：已知价格观察必须引用fixture证据")
        if self.cross_asset_confirmed and self.observation == "UNKNOWN":
            raise ValueError("PRICE_UNKNOWN：缺价格观察不能声称跨资产确认")
        return self


class OriginSourceSummary(DerivedEnvelope):
    event_ref: VersionRef
    as_of: UTCDateTime
    origin_count: Count
    independent_source_count: Count | None
    independence_status: Literal["KNOWN_ORIGIN_COUNT", "HOLD_INDEPENDENCE_UNKNOWN"]
    cluster_refs: Items[VersionRef]
    source_refs: Items[VersionRef]


class DiffusionSummary(DerivedEnvelope):
    event_ref: VersionRef
    observation_window: ObservationWindow
    source_ids: Items[Text]
    source_tiers: Items[Text]
    origin_count: Count
    previous_source_count: Count
    professional_sources: Count
    edit_count: Count
    delete_count: Count
    profile_refs: Items[VersionRef]
    source_refs: Items[VersionRef]


class EventPriceSummary(DerivedEnvelope):
    event_ref: VersionRef
    pricing_state: PricingState
    observation_refs: Items[VersionRef]
    scope_zh: Text = "仅已提供的Security fixture观察；不代表全市场或所有相关证券"


class StateTransition(DerivedEnvelope):
    event_ref: VersionRef
    dimension: Literal["FACT", "NARRATIVE", "PRICING"]
    previous_state: Text
    new_state: Text
    origin_source_summary_ref: VersionRef
    policy_ref: VersionRef
    outcome: Literal["APPLIED", "UNCHANGED", "HOLD"]

    @model_validator(mode="after")
    def gate(self):
        states = {"FACT": get_args(FactState), "NARRATIVE": get_args(NarrativeState), "PRICING": get_args(PricingState)}
        if self.previous_state not in states[self.dimension] or self.new_state not in states[self.dimension]:
            raise ValueError("STATE_ENUM：内部状态未知，拒绝写入")
        require_input_refs(self, (self.event_ref, self.origin_source_summary_ref, self.policy_ref, *self.evidence_refs))
        if not self.reason_codes:
            raise ValueError("STATE_REASON：转换必须有中文原因")
        return self


class EventClock(DerivedEnvelope):
    event_ref: VersionRef
    observed_at: UTCDateTime
    event_started_at: UTCDateTime | None
    first_seen_at: UTCDateTime
    last_material_update_at: UTCDateTime
    last_confirmation_at: UTCDateTime | None = None
    last_counterevidence_at: UTCDateTime | None = None
    last_narrative_acceleration_at: UTCDateTime | None = None
    last_market_reaction_at: UTCDateTime | None = None
    event_age_seconds: float | None
    observed_age_seconds: float
    time_since_last_material_update_seconds: float
    life_band: LifeBand = "UNKNOWN"

    @model_validator(mode="after")
    def gate(self):
        if self.observed_at > self.computed_at:
            raise ValueError("PIT_CLOCK：不能提前观察未来时钟")
        pairs = ((self.event_started_at, self.event_age_seconds), (self.first_seen_at, self.observed_age_seconds),
                 (self.last_material_update_at, self.time_since_last_material_update_seconds))
        for start, age in pairs:
            if start is None:
                if age is not None:
                    raise ValueError("CLOCK_UNKNOWN：未知起点的年龄必须null")
            elif age is None or age < 0 or abs(age - (self.observed_at - start).total_seconds()) > 1e-6:
                raise ValueError("CLOCK_AGE：事件年龄与实质更新年龄分别计算，不可混用")
        for stamp in (self.last_confirmation_at, self.last_counterevidence_at,
                      self.last_narrative_acceleration_at, self.last_market_reaction_at):
            if stamp and stamp > self.observed_at:
                raise ValueError("PIT_CLOCK：未来里程碑不可见")
        return self


class EventLineage(DerivedEnvelope):
    operation: Literal["MERGE", "SPLIT", "MUTATE", "ARCHIVE", "REACTIVATE"]
    parent_refs: Items[VersionRef]
    child_refs: Items[VersionRef]
    idempotency_key: Text
    interpretation_zh: Text


class RecomputeTrigger(DerivedEnvelope):
    event_ref: VersionRef
    trigger_reasons: Items[TriggerReason] = Field(min_length=1)
    priority: Priority
    idempotency_key: Text
    dispatch: Literal["READY", "COALESCED"]
    not_before: UTCDateTime
    cooldown_parent_ref: VersionRef | None = None


class EventStateSnapshot(DerivedEnvelope):
    event_ref: VersionRef
    fact_state: FactState
    narrative_state: NarrativeState
    pricing_state: PricingState
    clock_ref: VersionRef
    transition_refs: Items[VersionRef]
    assessment_refs: Items[VersionRef]
    priority: Priority
    lifecycle_status: Literal["ACTIVE", "ARCHIVED"]


SCHEMAS = {cls.__name__: cls for cls in (StatePolicy, EvidenceAssessment, SecurityPriceObservation,
    OriginSourceSummary, DiffusionSummary, EventPriceSummary, StateTransition, EventClock,
    EventLineage, RecomputeTrigger, EventStateSnapshot)}
