"""Phase 9 machine contract. Ordinals are not probabilities or return forecasts."""
from typing import Literal
from pydantic import Field, model_validator
from ..contracts.common import Contract, DerivedEnvelope, Items, Text, UTCDateTime, VersionRef, Band, Count
from ..contracts.models import require_input_refs
from ..ontology.contracts import Chinese
from ..graph.contracts import World
from ..exposures.contracts import ExposureType
from ..pricing.contracts import PricingMode, Recognition, PriceIn, Risk, Edge

POLICY = 'X_RANK_V0.1'
Grade = Literal['ALPHA1','ALPHA2','BETA','WATCH','OVERPRICED','REJECT']
Reason = Literal['INVALID_IDENTITY','INVALID_PATH','NARRATIVE_ONLY_FOR_ECONOMIC_ALPHA',
    'RESEARCH_HOLD','RESEARCH_NULL','RED_TEAM_INVALIDATED','PRICING_HOLD','NO_REMAINING_EDGE',
    'BLOCKING_MISSING_DATA','PIT_INVALID','DUPLICATE_SCOPE','UNSUPPORTED_BENEFICIARY','OTHER_EXPLICIT']


class RankEnvelope(DerivedEnvelope):
    as_of: UTCDateTime
    ranking_mode: PricingMode
    provenance_zh: Chinese
    qualification: Literal['ENGINEERING_ONLY'] = 'ENGINEERING_ONLY'
    formal_live_alpha: Literal[False] = False

    @model_validator(mode='after')
    def cutoff(self):
        if self.as_of > self.computed_at:
            raise ValueError('RANK_PIT')
        return self

    def is_visible(self, query):
        if query.mode == 'LIVE_FORWARD':
            return False  # No real-forward qualification in Phase 9.
        return super().is_visible(query)


class RankRules(Contract):
    grade_order: Items[Grade] = ('ALPHA1','ALPHA2','BETA','WATCH','OVERPRICED','REJECT')
    dimension_order: Items[Text] = ('remaining_edge','thesis_strength','next_buyer_status',
        'price_in_band','crowding_band','reversal_risk','alternative_cause_status','purity','missingness')
    ordinal_orders: dict[str, Items[Text]] = Field(default_factory=lambda: {
        'remaining_edge': ('STRONG','POSITIVE','THIN','NONE','NEGATIVE'),
        'thesis_strength': ('VERY_HIGH','HIGH','MEDIUM','LOW','VERY_LOW'),
        'next_buyer_status': ('SUPPORTED','PLAUSIBLE','WEAK','REJECTED'),
        'price_in_band': ('LOW','MEDIUM','HIGH','VERY_HIGH'),
        'crowding_band': ('LOW','MEDIUM','HIGH','EXTREME'),
        'reversal_risk': ('LOW','MEDIUM','HIGH','EXTREME'),
        'alternative_cause_status': ('CURRENT_EVENT_DOMINANT','MULTI_CAUSE','ALTERNATIVE_CAUSE_STRONG'),
        'purity': ('HIGH','LOW'), 'missingness': ('COMPLETE','SOFT_MISSING')})
    unknown_policy: dict[str, Literal['BLOCKING_UNKNOWN','SOFT_UNKNOWN']] = Field(default_factory=lambda: {
        'remaining_edge':'BLOCKING_UNKNOWN','thesis_strength':'BLOCKING_UNKNOWN',
        'next_buyer_status':'BLOCKING_UNKNOWN','price_in_band':'BLOCKING_UNKNOWN',
        'crowding_band':'BLOCKING_UNKNOWN','reversal_risk':'BLOCKING_UNKNOWN',
        'alternative_cause_status':'SOFT_UNKNOWN','purity':'SOFT_UNKNOWN','missingness':'SOFT_UNKNOWN'})
    unknown_sort: Literal['SEPARATE_KNOWLEDGE_BUCKET_AFTER_KNOWN'] = 'SEPARATE_KNOWLEDGE_BUCKET_AFTER_KNOWN'
    tie_break_policy: Literal['EVENT_SECURITY_PATH_STABLE_ID'] = 'EVENT_SECURITY_PATH_STABLE_ID'
    overpriced_policy: Literal['VALID_THESIS_HIGH_PRICING_NO_EDGE'] = 'VALID_THESIS_HIGH_PRICING_NO_EDGE'
    narrative_policy: Literal['SEPARATE_WATCH_NO_ECONOMIC_RESCUE'] = 'SEPARATE_WATCH_NO_ECONOMIC_RESCUE'
    missing_policy: Literal['HARD_HOLD_SOFT_CAP_ALPHA2'] = 'HARD_HOLD_SOFT_CAP_ALPHA2'
    execution_policy: Literal['DISPLAY_ONLY'] = 'DISPLAY_ONLY'
    alpha1_edges: Items[Edge] = ('STRONG','POSITIVE')
    alpha2_edges: Items[Edge] = ('STRONG','POSITIVE','THIN')
    alpha1_thesis: Items[Band] = ('HIGH','VERY_HIGH')
    alpha2_thesis: Items[Band] = ('MEDIUM','HIGH','VERY_HIGH')
    alpha1_buyers: Items[Text] = ('SUPPORTED',)
    alpha2_buyers: Items[Text] = ('SUPPORTED','PLAUSIBLE')
    alpha1_risks: Items[Text] = ('LOW','MEDIUM')
    alpha2_risks: Items[Text] = ('LOW','MEDIUM','HIGH')
    high_price_bands: Items[PriceIn] = ('HIGH','VERY_HIGH')
    no_edge_bands: Items[Edge] = ('NONE','NEGATIVE')
    high_revenue_share: float = Field(default=0.5, gt=0, le=1)
    broad_diffusion: float = Field(default=0.6, gt=0, le=1)
    beta_max_relative: float = Field(default=0.005, ge=0)

    @model_validator(mode='after')
    def policy_gate(self):
        defaults = type(self).model_fields
        if set(self.grade_order) != set(defaults['grade_order'].default) or len(self.grade_order)!=6:
            raise ValueError('RANK_GRADE_ORDER')
        if set(self.dimension_order)!=set(self.ordinal_orders) or len(set(self.dimension_order))!=len(self.dimension_order):
            raise ValueError('RANK_DIMENSIONS')
        if set(self.dimension_order)!=set(defaults['dimension_order'].default): raise ValueError('RANK_DIMENSION_ALLOWLIST')
        permitted=defaults['ordinal_orders'].default_factory()
        if any(set(self.ordinal_orders[n])!=set(permitted[n]) for n in permitted): raise ValueError('RANK_ORDINAL_ALLOWLIST')
        if set(self.unknown_policy)!=set(self.dimension_order): raise ValueError('RANK_UNKNOWN_POLICY')
        if any(not xs or len(xs)!=len(set(xs)) or set(xs)&{'UNKNOWN','HOLD'} for xs in self.ordinal_orders.values()):
            raise ValueError('RANK_ORDINAL')
        # Policy may tighten gates, never weaken immutable Alpha eligibility.
        if not set(self.alpha1_edges)<= {'STRONG','POSITIVE'} or not set(self.alpha2_edges)<={'STRONG','POSITIVE','THIN'}:
            raise ValueError('RANK_ALPHA_EDGE')
        if (not set(self.alpha1_thesis)<={'HIGH','VERY_HIGH'} or not set(self.alpha2_thesis)<={'MEDIUM','HIGH','VERY_HIGH'}
            or not set(self.alpha1_buyers)<={'SUPPORTED'} or not set(self.alpha2_buyers)<={'SUPPORTED','PLAUSIBLE'}
            or not set(self.alpha1_risks)<={'LOW','MEDIUM'} or not set(self.alpha2_risks)<={'LOW','MEDIUM','HIGH'}):
            raise ValueError('RANK_POLICY_CANNOT_RELAX_ALPHA')
        for name in ('remaining_edge','thesis_strength','next_buyer_status','price_in_band','crowding_band','reversal_risk'):
            if self.unknown_policy[name]!='BLOCKING_UNKNOWN': raise ValueError('RANK_CORE_UNKNOWN')
        return self


class RankPolicy(RankEnvelope):
    policy_id: Text
    policy_scope: Text = 'INDEPENDENT_A_SHARE_RESEARCH'
    rules: RankRules = RankRules()
    calibration_status: Literal['ENGINEERING_UNCALIBRATED'] = 'ENGINEERING_UNCALIBRATED'

    @model_validator(mode='after')
    def identity(self):
        if self.policy_id!=self.object_id: raise ValueError('RANK_POLICY_ID')
        return self


class RankRequest(Contract):
    snapshot_ref: VersionRef
    history_refs: Items[VersionRef]
    policy_ref: VersionRef
    as_of: UTCDateTime
    ranking_mode: PricingMode = 'ENGINEERING_FIXTURE'
    previous_package_ref: VersionRef | None = None

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.history_refs))!=len(self.history_refs): raise ValueError('DUPLICATE_SCOPE')
        return self


class RankDimensions(Contract):
    world: World = 'ECONOMIC'
    exposure_type: ExposureType = 'UNKNOWN'
    research_status: Literal['MOCK_PASS','HOLD','UNKNOWN'] = 'UNKNOWN'
    pricing_status: Literal['ENGINEERING_ONLY','HOLD','UNKNOWN'] = 'UNKNOWN'
    thesis_strength: Band = 'UNKNOWN'
    red_team_status: Literal['TARGET_WEAKENED','TARGET_INVALIDATED','ALT_STRONGER','NULL_PREFERRED','UNCHANGED','INCOMPLETE'] = 'INCOMPLETE'
    final_choice: Literal['TARGET','ALT','NULL','HOLD','UNKNOWN'] = 'UNKNOWN'
    decision_source: Literal['PRIMARY','RED_TEAM','ADJUDICATION','HOLD_GATE','UNKNOWN'] = 'UNKNOWN'
    recognition_state: Recognition = 'UNKNOWN'
    price_in_band: PriceIn = 'UNKNOWN'
    crowding_band: Risk = 'UNKNOWN'
    remaining_edge: Edge = 'UNKNOWN'
    reversal_risk: Risk = 'UNKNOWN'
    next_buyer_status: Literal['SUPPORTED','PLAUSIBLE','WEAK','UNKNOWN','REJECTED'] = 'UNKNOWN'
    alternative_cause_status: Literal['CURRENT_EVENT_DOMINANT','MULTI_CAUSE','ALTERNATIVE_CAUSE_STRONG','CAUSE_UNKNOWN'] = 'CAUSE_UNKNOWN'
    nonreaction_status: Literal['EXPLAINED_NON_REACTION','UNEXPLAINED_NON_REACTION','DATA_INSUFFICIENT','HOLD','UNKNOWN'] = 'UNKNOWN'
    purity: Literal['HIGH','LOW','UNKNOWN'] = 'UNKNOWN'
    systemic_basis: Literal['BROAD_SECTOR_RELATIVE_NEUTRAL','NONE','UNKNOWN'] = 'UNKNOWN'
    missingness: Literal['COMPLETE','SOFT_MISSING'] = 'COMPLETE'


class OrdinalDimension(Contract):
    dimension: Text
    raw_value: Text
    ordinal: Count | None
    knowledge: Literal['KNOWN','BLOCKING_UNKNOWN','SOFT_UNKNOWN']


class RankVector(RankEnvelope):
    candidate_grade: Grade
    processing_state: Literal['VALID','WATCH','OVERPRICED','REJECT','HOLD']
    dimensions: Items[OrdinalDimension]
    tie_break: Items[Text] = Field(min_length=3,max_length=3)
    policy_ref: VersionRef


class ExecutionEligibility(RankEnvelope):
    security_ref: VersionRef
    eligibility: Literal['ELIGIBLE','INELIGIBLE','UNKNOWN']
    purpose: Literal['DISPLAY_ONLY'] = 'DISPLAY_ONLY'
    market: Text
    board: Text
    security_status: Text
    account_policy_ref: VersionRef | None = None
    execution_reason_codes: Items[Text]


class AccountDisplayPolicy(RankEnvelope):
    allowed_boards: Items[Text] | None = None
    purpose: Literal['DISPLAY_ONLY'] = 'DISPLAY_ONLY'


class RejectReason(RankEnvelope):
    category: Reason
    detail_codes: Items[Text]
    explanation_zh: Chinese


class CandidateVersion(RankEnvelope, RankDimensions):
    candidate_id: Text
    event_ref: VersionRef | None
    security_ref: VersionRef
    company_ref: VersionRef | None
    path_ref: VersionRef | None
    history_ref: VersionRef | None
    analysis_ref: VersionRef | None
    pricing_assessment_ref: VersionRef | None
    candidate_grade: Grade
    processing_state: Literal['VALID','WATCH','OVERPRICED','REJECT','HOLD']
    mapping_state: Text
    positive_path_refs: Items[VersionRef]
    negative_path_refs: Items[VersionRef]
    counter_refs: Items[VersionRef]
    supporting_evidence_refs: Items[VersionRef]
    metric_refs: Items[VersionRef]
    countercase: Items[Chinese]
    failure_conditions: Items[Chinese]
    unknowns: Items[Text]
    missing_dimensions: Items[Text]
    rank_vector_ref: VersionRef
    execution_eligibility_ref: VersionRef
    reject_reason_refs: Items[VersionRef]
    candidate_reason_codes: Items[Text]
    grade_reason_zh: Chinese

    @model_validator(mode='after')
    def grade_gate(self):
        if self.candidate_id!=self.object_id: raise ValueError('CANDIDATE_ID')
        if self.candidate_grade in ('ALPHA1','ALPHA2','BETA') and (not self.countercase or not self.failure_conditions):
            raise ValueError('RANK_COUNTERCASE_REQUIRED')
        if self.candidate_grade in ('ALPHA1','ALPHA2'):
            if (self.world!='ECONOMIC' or self.processing_state!='VALID' or self.research_status!='MOCK_PASS'
                or self.pricing_status!='ENGINEERING_ONLY' or self.final_choice not in ('TARGET','ALT')
                or self.decision_source in ('HOLD_GATE','UNKNOWN') or self.red_team_status in ('INCOMPLETE','TARGET_INVALIDATED','NULL_PREFERRED')
                or self.remaining_edge not in ('STRONG','POSITIVE','THIN')):
                raise ValueError('RANK_ALPHA_GATE')
            if self.candidate_grade=='ALPHA1' and self.remaining_edge=='THIN': raise ValueError('RANK_ALPHA1_EDGE')
        return self


class CandidateChange(RankEnvelope):
    previous_candidate_ref: VersionRef | None
    current_candidate_ref: VersionRef | None
    from_grade: Grade | None
    to_grade: Grade | None
    grade_change: Literal['NEW','UPGRADED','DOWNGRADED','UNCHANGED','REMOVED','REJECTED','OVERPRICED']
    previous_rank: Count | None
    current_rank: Count | None
    rank_change: int | None
    changed_dimensions: Items[Text]
    change_reason_codes: Items[Text]


class RankEntry(Contract):
    candidate_ref: VersionRef
    rank: Count
    grade: Grade
    world: World


class SecuritySummary(Contract):
    security_ref: VersionRef
    world: World
    winner_path_ref: VersionRef | None
    all_candidate_path_refs: Items[VersionRef]
    positive_path_refs: Items[VersionRef]
    negative_path_refs: Items[VersionRef]


class RankSnapshot(RankEnvelope):
    entries: Items[RankEntry]
    economic_ranking: Items[VersionRef]
    narrative_ranking: Items[VersionRef]
    economic_alpha_refs: Items[VersionRef]
    beta_refs: Items[VersionRef]
    security_summaries: Items[SecuritySummary]
    policy_ref: VersionRef

    @model_validator(mode='after')
    def ranking_partition(self):
        if len({e.candidate_ref for e in self.entries})!=len(self.entries): raise ValueError('RANK_DUPLICATE_ENTRY')
        for world,group in (('ECONOMIC',self.economic_ranking),('NARRATIVE',self.narrative_ranking)):
            entries=[e for e in self.entries if e.world==world]
            if tuple(e.candidate_ref for e in entries)!=group or [e.rank for e in entries]!=list(range(1,len(entries)+1)):
                raise ValueError('RANK_WORLD_ORDER')
        if self.economic_alpha_refs!=tuple(e.candidate_ref for e in self.entries if e.world=='ECONOMIC' and e.grade in ('ALPHA1','ALPHA2')):
            raise ValueError('RANK_ECONOMIC_ALPHA_PARTITION')
        if self.beta_refs!=tuple(e.candidate_ref for e in self.entries if e.grade=='BETA'): raise ValueError('RANK_BETA_PARTITION')
        return self


class UniverseSample(Contract):
    security_ref: VersionRef
    universe_decision: Literal['INCLUDED','EXCLUDED','HOLD']
    candidate_refs: Items[VersionRef]
    reason_codes: Items[Text]


class RankManifest(RankEnvelope):
    snapshot_ref: VersionRef
    history_refs: Items[VersionRef]
    samples: Items[UniverseSample]
    candidate_refs: Items[VersionRef]
    outside_universe_candidate_refs: Items[VersionRef] = ()
    universe_total: Count
    total: Count
    eligible_for_ranking: Count
    alpha1: Count
    alpha2: Count
    beta: Count
    watch: Count
    overpriced: Count
    reject: Count
    hold: Count
    coverage_status: Literal['HOLD_REAL_COMPANY_EXPOSURE_COVERAGE'] = 'HOLD_REAL_COMPANY_EXPOSURE_COVERAGE'

    @model_validator(mode='after')
    def totals(self):
        if (self.universe_total!=len(self.samples) or len({x.security_ref.object_id for x in self.samples})!=len(self.samples)
            or self.total!=len(self.candidate_refs) or len(set(self.candidate_refs))!=self.total
            or self.total!=self.alpha1+self.alpha2+self.beta+self.watch+self.overpriced+self.reject
            or self.eligible_for_ranking!=self.alpha1+self.alpha2+self.beta):
            raise ValueError('RANK_MANIFEST_COUNTS')
        if any(not s.candidate_refs for s in self.samples): raise ValueError('RANK_MANIFEST_OMISSION')
        partition=[r for s in self.samples for r in s.candidate_refs]+list(self.outside_universe_candidate_refs)
        if len(set(partition))!=len(partition) or set(partition)!=set(self.candidate_refs): raise ValueError('RANK_MANIFEST_PARTITION')
        return self


class OpportunityPackage(RankEnvelope):
    request: RankRequest
    candidate_refs: Items[VersionRef]
    rank_snapshot_ref: VersionRef
    manifest_ref: VersionRef
    change_refs: Items[VersionRef]
    empty_opportunity_list: bool
    hold_reasons: Items[Text]

    @model_validator(mode='after')
    def inputs(self):
        require_input_refs(self, (*self.candidate_refs,self.rank_snapshot_ref,self.manifest_ref,*self.change_refs,
            self.request.snapshot_ref,self.request.policy_ref,*self.request.history_refs,
            *([self.request.previous_package_ref] if self.request.previous_package_ref else [])))
        if self.as_of!=self.request.as_of or self.ranking_mode!=self.request.ranking_mode: raise ValueError('RANK_REQUEST')
        return self


SCHEMAS={c.__name__:c for c in (RankPolicy,RankVector,AccountDisplayPolicy,ExecutionEligibility,RejectReason,CandidateVersion,
    CandidateChange,RankSnapshot,RankManifest,OpportunityPackage)}
