"""研究机器契约；只保存公开结论依据，禁止私有思维链。"""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from ..contracts.common import Contract, DerivedEnvelope, Items, Text, UTCDateTime, VersionRef, Count, Band, SHA256
from ..contracts.models import require_input_refs
from ..ontology.contracts import Chinese

POLICY = 'X_RESEARCH_V0.1'
CallType = Literal['PRIMARY', 'RED_TEAM', 'ADJUDICATION']
DecisionSource = Literal['PRIMARY','RED_TEAM','ADJUDICATION','HOLD_GATE']
Commentary = Annotated[Chinese, Field(description='INFERENCE_ONLY / RESEARCH_COMMENTARY：无FACT资格，不得作为新增事实输入')]
ResearchMode = Literal['MOCK_FORWARD', 'HISTORICAL_REPLAY']


class ResearchEnvelope(DerivedEnvelope):
    as_of: UTCDateTime
    provenance_zh: Chinese

    @model_validator(mode='after')
    def knowledge_time(self):
        if self.as_of > self.computed_at:
            raise ValueError('RESEARCH_PIT：截止时间不能晚于完成时间')
        return self


class BudgetPolicy(Contract):
    max_requests: Annotated[int, Field(ge=0, le=4)] = 3
    max_output_tokens_total: Count = 12000
    max_cost: Annotated[float, Field(ge=0)] | None = None


class ResearchModeEnvelope(ResearchEnvelope):
    research_mode: ResearchMode

    def is_visible(self, query):
        if query.mode=='LIVE_FORWARD' and self.research_mode=='HISTORICAL_REPLAY':
            return False
        return super().is_visible(query)


class PromptVersion(ResearchEnvelope):
    primary_zh: Chinese
    red_team_zh: Chinese
    adjudication_zh: Chinese


class ModelConfig(ResearchEnvelope):
    provider_id: Text
    model_identifier: Text
    temperature: Annotated[float, Field(ge=0, le=2)] = 0.0
    max_output: Annotated[int, Field(gt=0, le=16000)] = 2048
    timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 10.0
    retry_limit: Annotated[int, Field(ge=0, le=1)] = 0
    budget_policy: BudgetPolicy = BudgetPolicy()
    prompt_version_ref: VersionRef
    allow_adjudication: bool = True

    @model_validator(mode='after')
    def references(self):
        require_input_refs(self, (self.prompt_version_ref,))
        return self


class SearchCoverage(ResearchEnvelope):
    event_ref: VersionRef
    mapping_history_ref: VersionRef
    event_evidence_count: Count
    first_hand_source_count: Count
    origin_count: Count
    independent_source_count: Count | None
    independence_status: Text
    positive_path_count: Count
    negative_path_count: Count
    narrative_path_count: Count
    exposure_coverage_status: Literal['HOLD_REAL_COMPANY_EXPOSURE_COVERAGE']
    critical_unknown: bool
    has_hold: bool
    gaps: Items[Text]
    search_scope: Literal['FIXED_PACKET_ONLY_NO_EXTERNAL_SEARCH'] = 'FIXED_PACKET_ONLY_NO_EXTERNAL_SEARCH'


class ResearchPacket(ResearchModeEnvelope):
    packet_id: Text
    packet_hash: SHA256
    event_ref: VersionRef
    event_state_ref: VersionRef | None
    mapping_history_ref: VersionRef
    path_refs: Items[VersionRef]
    assessment_refs: Items[VersionRef]
    selection_manifest_ref: VersionRef | None
    positive_path_refs: Items[VersionRef]
    negative_path_refs: Items[VersionRef]
    narrative_path_refs: Items[VersionRef]
    counter_path_refs: Items[VersionRef]
    company_refs: Items[VersionRef]
    security_refs: Items[VersionRef]
    origin_refs: Items[VersionRef]
    metric_refs: Items[VersionRef]
    fact_object_refs: Items[VersionRef]
    search_coverage_ref: VersionRef
    prompt_version_ref: VersionRef
    model_config_ref: VersionRef
    gate_reasons: Items[Text]
    research_mode: ResearchMode
    eligibility: Literal['ELIGIBLE_KNOWN_SUBSET', 'REVIEW_ONLY']

    @model_validator(mode='after')
    def references(self):
        if self.packet_id != self.object_id:
            raise ValueError('PACKET_ID：固定身份不一致')
        originals=(self.event_ref,self.mapping_history_ref,self.prompt_version_ref,self.model_config_ref,
            *self.path_refs,*self.assessment_refs,*self.company_refs,*self.security_refs,*self.origin_refs,
            *self.metric_refs,*self.fact_object_refs,*self.evidence_refs,
            *(r for r in (self.event_state_ref,self.selection_manifest_ref) if r))
        require_input_refs(self, (*originals,self.search_coverage_ref))
        keys={(r.object_id,r.version) for r in originals}
        if any((r.object_id,r.version) in keys and r.available_at>self.as_of for r in self.input_version_refs):
            raise ValueError('PACKET_PIT：原始研究输入必须在截止点已知')
        if (self.eligibility=='REVIEW_ONLY') != bool(self.gate_reasons):
            raise ValueError('PACKET_GATE：降级必须说明原因')
        for group in (self.positive_path_refs,self.negative_path_refs,self.narrative_path_refs,self.counter_path_refs):
            if any(r not in self.path_refs for r in group):
                raise ValueError('PACKET_PATH：分组必须来自本包')
        return self


class NumericClaim(Contract):
    claim: Text = Field(description='必须等于原Metric的metric_type，禁止换成其他经济口径')
    numeric_value: float
    unit: Text
    currency: Text | None
    source_ref: VersionRef
    source_span_ref: Literal['REPORTED_NUMERATOR', 'SAME_BASIS_RATIO']


class ResearchStatement(Contract):
    kind: Literal['CONFIRMED_FACT','SUPPORTED_INFERENCE','HYPOTHESIS','UNKNOWN','COUNTEREVIDENCE']
    text_zh: Chinese
    evidence_ref: VersionRef | None = None
    quoted_span: Text | None = None


class Hypothesis(Contract):
    hypothesis_id: Text
    type: Literal['TARGET','ALT','NULL']
    company_ref: VersionRef | None = None
    security_ref: VersionRef | None = None
    supporting_path_refs: Items[VersionRef] = ()
    supporting_evidence_refs: Items[VersionRef] = ()
    counter_path_refs: Items[VersionRef] = ()
    assumptions: Annotated[Items[Commentary], Field(min_length=1)]
    failure_conditions: Annotated[Items[Commentary], Field(min_length=1)]
    unknowns: Items[Commentary]
    confidence_band: Band
    reasoning_summary_zh: Commentary
    statements: Items[ResearchStatement] = ()
    numeric_claims: Items[NumericClaim] = ()


class HypothesisSet(Contract):
    target: Hypothesis
    alternatives: Items[Hypothesis]
    null_hypothesis: Hypothesis
    selected_id: Text
    alternative_search_gap_zh: Chinese | None = None

    @model_validator(mode='after')
    def hypotheses(self):
        values=(self.target,*self.alternatives,self.null_hypothesis)
        if self.target.type!='TARGET' or self.null_hypothesis.type!='NULL' or any(h.type!='ALT' for h in self.alternatives):
            raise ValueError('HYPOTHESIS_KIND：必须保留TARGET/ALT/NULL角色')
        ids={h.hypothesis_id for h in values}
        if len(ids)!=len(values) or self.selected_id not in ids:
            raise ValueError('HYPOTHESIS_ID：选择必须来自无重复假设集合')
        if not self.alternatives and not self.alternative_search_gap_zh:
            raise ValueError('ALT_COVERAGE：找不到合法替代时必须记录范围与缺口')
        if self.null_hypothesis.company_ref or self.null_hypothesis.security_ref or self.null_hypothesis.supporting_path_refs:
            raise ValueError('NULL_FIRST_CLASS：NULL不是一只被强选的证券')
        return self


class RedTeamReport(Contract):
    verdict: Literal['TARGET_WEAKENED','TARGET_INVALIDATED','ALT_STRONGER','NULL_PREFERRED','UNCHANGED']
    recommended_id: Text
    evidence_refs: Items[VersionRef]
    counter_path_refs: Items[VersionRef]
    challenges_zh: Annotated[Items[Commentary], Field(min_length=1)]
    failure_conditions_zh: Annotated[Items[Commentary], Field(min_length=1)]
    reasoning_summary_zh: Commentary
    numeric_claims: Items[NumericClaim] = ()
    statements: Items[ResearchStatement] = ()


class Adjudication(Contract):
    statements: Items[ResearchStatement] = ()
    selected_id: Text
    evidence_refs: Items[VersionRef]
    reasoning_summary_zh: Commentary


class ModelResult(ResearchModeEnvelope):
    packet_ref: VersionRef
    call_type: CallType
    primary: HypothesisSet | None = None
    red_team: RedTeamReport | None = None
    adjudication: Adjudication | None = None
    cache_key: SHA256
    response_hash: SHA256

    @model_validator(mode='after')
    def single_result(self):
        values={'PRIMARY':self.primary,'RED_TEAM':self.red_team,'ADJUDICATION':self.adjudication}
        if values[self.call_type] is None or sum(v is not None for v in values.values())!=1:
            raise ValueError('MODEL_RESULT：每次调用只有所属角色的结构化结果')
        require_input_refs(self,(self.packet_ref,))
        return self


class CostLedger(ResearchEnvelope):
    analysis_run_id: Text
    provider: Text
    model: Text
    call_type: CallType
    request_count: Literal[0,1]
    input_usage: Count | None = None
    output_usage: Count | None = None
    reserved_output: Count
    estimated_cost: float | None = None
    actual_cost: float | None = None
    cost_status: Literal['UNKNOWN'] = 'UNKNOWN'
    timeout: bool = False
    retry: bool = False
    cache_hit: bool = False
    call_status: Literal['RESERVED','SUCCESS','TIMEOUT','INVALID_SCHEMA','INVALID_REFERENCE','INVALID_NUMERIC_CLAIM',
        'BUDGET_EXHAUSTED','PROVIDER_UNAVAILABLE','PROMPT_INJECTION_REJECTED','HOLD']
    cache_key: SHA256
    response_hash: SHA256 | None = None


class AnalysisStart(ResearchEnvelope):
    packet_ref: VersionRef
    started_at: UTCDateTime
    request_hash: SHA256


class AnalysisRun(ResearchModeEnvelope):
    packet_ref: VersionRef
    primary_result_ref: VersionRef | None
    red_team_ref: VersionRef | None
    adjudication_ref: VersionRef | None
    decision_source: DecisionSource
    final_result_ref: VersionRef | None
    final_hypothesis_id: Text | None
    final_choice: Literal['TARGET','ALT','NULL','HOLD']
    model_config_refs: Items[VersionRef]
    prompt_refs: Items[VersionRef]
    cost_ledger_refs: Items[VersionRef]
    search_coverage_ref: VersionRef
    started_at: UTCDateTime
    completed_at: UTCDateTime
    research_mode: ResearchMode
    analysis_status: Literal['MOCK_PASS','HOLD']
    hold_reasons: Items[Text]

    @model_validator(mode='after')
    def completed(self):
        if not self.as_of<=self.started_at<=self.completed_at<=self.available_at:
            raise ValueError('ANALYSIS_TIME：实际完成后才能发布')
        if self.final_choice in ('TARGET','ALT') and (self.red_team_ref is None or self.analysis_status!='MOCK_PASS'):
            raise ValueError('RED_TEAM_REQUIRED：未完成反方不得发布主要假设')
        sources={'PRIMARY':self.primary_result_ref,'RED_TEAM':self.red_team_ref,'ADJUDICATION':self.adjudication_ref}
        if self.analysis_status=='HOLD':
            if self.decision_source!='HOLD_GATE' or self.final_result_ref is not None or self.final_hypothesis_id is not None or self.final_choice not in ('HOLD','NULL'):
                raise ValueError('DECISION_SOURCE：HOLD只能由Gate决定，无正式模型选择或引用')
        elif (self.decision_source=='HOLD_GATE' or self.final_result_ref is None
              or self.final_result_ref!=sources.get(self.decision_source)
              or self.final_hypothesis_id is None or self.final_choice=='HOLD'
              or (self.adjudication_ref is not None and self.decision_source!='ADJUDICATION')):
            raise ValueError('DECISION_SOURCE：正式选择必须对应唯一决定来源')
        require_input_refs(self,(self.packet_ref,self.search_coverage_ref,*self.model_config_refs,*self.prompt_refs,
            *self.cost_ledger_refs,*(r for r in (self.primary_result_ref,self.red_team_ref,self.adjudication_ref,self.final_result_ref) if r)))
        return self


SCHEMAS={c.__name__:c for c in (PromptVersion,ModelConfig,SearchCoverage,ResearchPacket,ModelResult,CostLedger,AnalysisStart,AnalysisRun)}
OUTPUT_SCHEMAS={c.__name__:c for c in (HypothesisSet,RedTeamReport,Adjudication,NumericClaim,ResearchStatement)}
