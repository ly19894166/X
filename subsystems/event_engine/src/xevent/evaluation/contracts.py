"""Pre-registered, immutable evaluation contracts; no account PnL or trade commands."""
from typing import Literal
from pydantic import Field, model_validator
from ..contracts.common import Contract, DerivedEnvelope, Items, Text, UTCDateTime, VersionRef, Count, SHA256
from ..ranking.contracts import OpportunityPackage, RankManifest, RankSnapshot, CandidateVersion
from ..pricing.contracts import MarketObservation, ProviderQualification, AdjustmentBasis, MarketSession
from ..contracts.models import require_input_refs

POLICY = 'X_EVALUATION_V0.1'
WINDOWS = ('H30', 'T_CLOSE', 'T1_0935', 'T1_1000', 'T1_CLOSE', 'T3_CLOSE')
WindowName = Literal['H30','T_CLOSE','T1_0935','T1_1000','T1_CLOSE','T3_CLOSE']
EvaluationMode = Literal['ENGINEERING_FIXTURE','MOCK_FORWARD','PUBLIC_PIT_RESEARCH','HISTORICAL_REPLAY','REAL_FORWARD']
Executable = Literal['EXECUTABLE','LIMIT_BLOCKED','SUSPENDED','NO_LIQUIDITY','QUOTE_MISSING','UNKNOWN_EXECUTABILITY']


class EvaluationEnvelope(DerivedEnvelope):
    as_of: UTCDateTime
    evaluation_mode: EvaluationMode
    provenance: Text
    qualification: Literal['ENGINEERING_ONLY'] = 'ENGINEERING_ONLY'
    formal_live_alpha: Literal[False] = False
    revision_reason: Text | None = None

    @model_validator(mode='after')
    def times(self):
        if self.as_of > self.computed_at: raise ValueError('EVALUATION_PIT')
        if self.version > 1 and not self.revision_reason: raise ValueError('REVISION_REASON_REQUIRED')
        return self

    def is_visible(self, query):
        if query.mode == 'LIVE_FORWARD': return False
        return super().is_visible(query)


class SessionDay(Contract):
    trading_date: Text
    intervals: Items[Items[UTCDateTime]]

    @model_validator(mode='after')
    def ordered(self):
        if not self.intervals or any(len(pair)!=2 for pair in self.intervals): raise ValueError('CALENDAR_INTERVAL')
        if any(a >= b for a,b in self.intervals): raise ValueError('CALENDAR_INTERVAL')
        if any(a[1] > b[0] for a,b in zip(self.intervals,self.intervals[1:])): raise ValueError('CALENDAR_OVERLAP')
        return self


class SettlementCalendar(EvaluationEnvelope):
    """Fixed projection of existing MarketSession intervals, including declared closed dates."""
    session: MarketSession
    coverage_start: UTCDateTime
    coverage_end: UTCDateTime
    days: Items[SessionDay]
    closed_dates: Items[Text]
    qualification_status: Literal['ENGINEERING_QUALIFIED','HOLD']

    @model_validator(mode='after')
    def calendar(self):
        dates = [d.trading_date for d in self.days]
        if dates != sorted(set(dates)) or set(dates)&set(self.closed_dates): raise ValueError('CALENDAR_DATES')
        flat = tuple(pair for d in self.days for pair in d.intervals)
        if flat != tuple((w.start,w.end) for w in self.session.intervals): raise ValueError('CALENDAR_SESSION_PROJECTION')
        if not self.coverage_start < self.coverage_end: raise ValueError('CALENDAR_COVERAGE')
        if any(a < self.coverage_start or b > self.coverage_end for a,b in flat): raise ValueError('CALENDAR_COVERAGE')
        return self


class EvaluationRules(Contract):
    windows: Items[WindowName] = WINDOWS
    entry_policy: Literal['FIRST_QUOTE_AFTER_PACKAGE_DELAY_NEXT_ELIGIBLE_SESSION'] = 'FIRST_QUOTE_AFTER_PACKAGE_DELAY_NEXT_ELIGIBLE_SESSION'
    delay_seconds: int = Field(default=60, ge=0)
    quote_type: Literal['PRICE'] = 'PRICE'
    exit_policy: Literal['EXACT_WINDOW_END'] = 'EXACT_WINDOW_END'
    max_entry_wait_seconds: int = Field(default=300, ge=0)
    late_tolerance_seconds: int = Field(default=60, ge=0)
    max_quote_latency_seconds: int = Field(default=5, ge=0)
    commission: float = Field(default=0.0003, ge=0, le=0.1)
    tax: float = Field(default=0.0005, ge=0, le=0.1)
    other_cost: float = Field(default=0.0, ge=0, le=0.1)
    slippage: float = Field(default=0.0005, ge=0, le=0.1)
    cost_basis: Literal['ENGINEERING_ASSUMPTION_UNCALIBRATED_PER_SIDE'] = 'ENGINEERING_ASSUMPTION_UNCALIBRATED_PER_SIDE'
    limit_policy: Literal['EXPLICIT_EXECUTABILITY_PROOF_OR_HOLD'] = 'EXPLICIT_EXECUTABILITY_PROOF_OR_HOLD'
    suspension_policy: Literal['RETAIN_UNSETTLED'] = 'RETAIN_UNSETTLED'
    missing_policy: Literal['RETAIN_DENOMINATOR_NO_IMPUTATION'] = 'RETAIN_DENOMINATOR_NO_IMPUTATION'
    t_plus_one: Literal[True] = True
    diagnostic_policy: Literal['COMPLETE_TRADING_MINUTE_GRID_ONLY'] = 'COMPLETE_TRADING_MINUTE_GRID_ONLY'
    min_candidates: int = Field(default=30, ge=1)
    min_clusters: int = Field(default=10, ge=2)
    min_coverage: float = Field(default=0.8, gt=0, le=1)
    interval_method: Literal['EVENT_CLUSTER_BOOTSTRAP_PERCENTILE'] = 'EVENT_CLUSTER_BOOTSTRAP_PERCENTILE'
    bootstrap_seed: int = 104729
    bootstrap_replicates: int = Field(default=500, ge=100, le=10000)
    confidence_level: Literal[0.95] = 0.95
    cluster_policy: Literal['FROZEN_EVENT_OR_SHARED_ORIGIN_CONNECTED_COMPONENT'] = 'FROZEN_EVENT_OR_SHARED_ORIGIN_CONNECTED_COMPONENT'
    baselines: Items[Literal['BASELINE_ALL_ECONOMIC_VALID','BASELINE_BETA','BASELINE_WATCH']] = ('BASELINE_ALL_ECONOMIC_VALID','BASELINE_BETA','BASELINE_WATCH')
    ablations: Items[Literal['NO_RANKING','NO_PRICE_IN']] = ('NO_RANKING','NO_PRICE_IN')
    calibration: Literal['ENGINEERING_UNCALIBRATED'] = 'ENGINEERING_UNCALIBRATED'

    @model_validator(mode='after')
    def frozen(self):
        if tuple(self.windows) != WINDOWS: raise ValueError('ALL_PREREGISTERED_WINDOWS_REQUIRED')
        if len(set(self.baselines))!=len(self.baselines) or len(set(self.ablations))!=len(self.ablations): raise ValueError('DUPLICATE_GROUP')
        return self


class EvaluationPlan(EvaluationEnvelope):
    epoch: Text
    rank_policy_ref: VersionRef
    calendar_ref: VersionRef
    rules: EvaluationRules
    registration_start: UTCDateTime
    registration_end: UTCDateTime
    expected_runs: Count
    report_metrics: Items[Text] = ('sample_n','event_cluster_n','coverage_rate','empty_list_rate','settlement_rate',
        'positive_return_rate','negative_return_rate','mean_return','median_return','MFE','MAE')

    @model_validator(mode='after')
    def preregister(self):
        if not self.available_at <= self.registration_start < self.registration_end: raise ValueError('PLAN_PREREGISTRATION')
        require_input_refs(self,(self.calendar_ref,))
        return self


class FrozenFeatureArchive(EvaluationEnvelope):
    """Verified copy on label side. The source feature database remains read-only."""
    package: OpportunityPackage
    manifest: RankManifest
    snapshot: RankSnapshot
    candidates: Items[CandidateVersion]
    feature_hashes: dict[str, SHA256]
    candidate_clusters: dict[str, Text]
    candidate_cluster_tokens: dict[str, Items[Text]]
    event_cluster_refs: Items[VersionRef]
    source_database_identity: SHA256

    @model_validator(mode='after')
    def partition(self):
        refs = tuple(VersionRef(object_id=c.object_id,version=c.version) for c in self.candidates)
        if refs != self.package.candidate_refs or refs != self.manifest.candidate_refs: raise ValueError('FROZEN_SAMPLE_OMISSION')
        if set(self.candidate_clusters)!= {c.object_id for c in self.candidates}: raise ValueError('CLUSTER_PARTITION')
        if set(self.candidate_cluster_tokens)!=set(self.candidate_clusters) or any(not xs for xs in self.candidate_cluster_tokens.values()):
            raise ValueError('CLUSTER_TOKEN_PARTITION')
        if self.package.manifest_ref != VersionRef(object_id=self.manifest.object_id,version=self.manifest.version): raise ValueError('MANIFEST_REFERENCE')
        if self.package.rank_snapshot_ref != VersionRef(object_id=self.snapshot.object_id,version=self.snapshot.version): raise ValueError('SNAPSHOT_REFERENCE')
        if any(c.available_at > self.package.available_at for c in self.candidates): raise ValueError('FEATURE_PIT')
        return self


class ResearchRunManifest(EvaluationEnvelope):
    shadow_run_id: Text
    archive_ref: VersionRef
    opportunity_package_ref: VersionRef
    rank_manifest_ref: VersionRef
    rank_snapshot_ref: VersionRef
    evaluation_plan_ref: VersionRef
    feature_cutoff: UTCDateTime
    package_available_at: UTCDateTime
    ranking_mode: Text
    research_universe_ref: VersionRef
    universe_total: Count
    candidate_total: Count
    grade_counts: dict[str, Count]
    hold_count: Count
    empty_opportunity_list: bool
    eligible_evaluation_groups: dict[str, Items[VersionRef]]
    event_cluster_refs: Items[VersionRef]
    security_refs: Items[VersionRef]
    manifest_hash: SHA256
    epoch: Text
    forward_identity: Literal['ORIGINAL_REGISTRATION','HISTORICAL_RECOMPUTE']

    @property
    def manifest_available_at(self): return self.available_at

    @model_validator(mode='after')
    def frozen_counts(self):
        require_input_refs(self,(self.archive_ref,self.evaluation_plan_ref))
        if sum(self.grade_counts.values())!=self.candidate_total or self.hold_count>self.candidate_total: raise ValueError('RUN_COUNTS')
        all_refs=self.eligible_evaluation_groups.get('ALL_FROZEN',())
        if len(all_refs)!=self.candidate_total or len(set(all_refs))!=len(all_refs): raise ValueError('RUN_DENOMINATOR')
        if any(not set(rs)<=set(all_refs) for rs in self.eligible_evaluation_groups.values()): raise ValueError('RUN_GROUP_MEMBERSHIP')
        if not self.feature_cutoff<=self.package_available_at<=self.available_at: raise ValueError('RUN_PIT')
        return self


class OutcomeQuote(EvaluationEnvelope):
    observation: MarketObservation
    provider_qualification: ProviderQualification
    adjustment: AdjustmentBasis
    session: MarketSession
    entry_executability: Executable
    exit_executability: Executable
    execution_evidence: Text | None = None
    limit_state: Literal['NONE','OPEN_LIMIT','ONE_PRICE_LIMIT','DOWN_LIMIT','TOUCHED_LIMIT','UNKNOWN'] = 'UNKNOWN'
    traded_volume: float | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def quote(self):
        q = self.observation
        from ..contracts.bundle import content_digest
        if any(o.content_hash!=content_digest(o) for o in (q,self.provider_qualification,self.adjustment,self.session)):
            raise ValueError('QUOTE_ARCHIVE_HASH')
        for r,o in ((q.provider_ref,self.provider_qualification),(q.adjustment_ref,self.adjustment),(q.session_ref,self.session)):
            if r != VersionRef(object_id=o.object_id,version=o.version): raise ValueError('QUOTE_REFERENCE')
        if any(o.available_at > self.available_at for o in (q,self.provider_qualification,self.adjustment,self.session)): raise ValueError('QUOTE_INPUT_PIT')
        if q.instrument_ref!=self.adjustment.instrument_ref or q.instrument_ref!=self.session.instrument_ref: raise ValueError('QUOTE_INSTRUMENT')
        if q.source_ref!=self.provider_qualification.source_ref or q.provider!=self.provider_qualification.provider: raise ValueError('QUOTE_PROVIDER')
        if q.adjustment_type!=self.adjustment.adjustment_type: raise ValueError('QUOTE_ADJUSTMENT')
        if 'EXECUTABLE' in (self.entry_executability,self.exit_executability):
            if not self.execution_evidence or not self.traded_volume or self.limit_state!='NONE': raise ValueError('EXECUTABILITY_PROOF_REQUIRED')
        return self


class SettlementWindow(Contract):
    name: WindowName
    start: UTCDateTime
    end: UTCDateTime
    trading_date: Text

    @model_validator(mode='after')
    def ordered(self):
        if self.end<self.start: raise ValueError('SETTLEMENT_WINDOW_ORDER')
        return self


class ExecutionSimulation(Contract):
    purpose: Literal['SIMULATED_REALIZABLE'] = 'SIMULATED_REALIZABLE'
    entry_status: Executable
    exit_status: Executable
    settlement_kind: Literal['OBSERVATIONAL_OUTCOME','REALIZABLE_SETTLEMENT']
    t_plus_one_satisfied: bool
    simulated_return: float | None
    cost_plan_ref: VersionRef
    reason_codes: Items[Text]

    @model_validator(mode='after')
    def executable(self):
        if self.simulated_return is not None and (not self.t_plus_one_satisfied or self.entry_status!='EXECUTABLE'
            or self.exit_status!='EXECUTABLE' or self.settlement_kind!='REALIZABLE_SETTLEMENT'): raise ValueError('NOT_REALIZABLE')
        return self


class SampleQuality(EvaluationEnvelope):
    research_run_ref: VersionRef
    candidate_ref: VersionRef
    window: SettlementWindow
    quality: Literal['QUALIFIED','PARTIAL','UNSETTLED','MARKET_DATA_HOLD','EXECUTION_HOLD','PIT_HOLD']
    quality_reasons: Items[Text]
    reference_eligible: bool
    simulated_eligible: bool

    @model_validator(mode='after')
    def eligibility(self):
        require_input_refs(self,(self.research_run_ref,))
        if self.quality!='QUALIFIED' and not self.quality_reasons: raise ValueError('QUALITY_REASON')
        if self.simulated_eligible and not self.reference_eligible: raise ValueError('QUALITY_ELIGIBILITY')
        if (self.quality=='QUALIFIED')!=self.simulated_eligible: raise ValueError('QUALITY_ELIGIBILITY')
        return self


class Outcome(EvaluationEnvelope):
    research_run_ref: VersionRef
    candidate_ref: VersionRef
    window: SettlementWindow
    plan_ref: VersionRef
    entry_quote_ref: VersionRef | None
    exit_quote_ref: VersionRef | None
    observation_refs: Items[VersionRef]
    reference_return: float | None
    simulation: ExecutionSimulation
    quality_ref: VersionRef
    mfe: float | None
    mae: float | None
    diagnostic_purpose: Literal['DIAGNOSTIC_ONLY'] = 'DIAGNOSTIC_ONLY'
    diagnostic_reason: Text | None
    late: bool

    @model_validator(mode='after')
    def window_gate(self):
        if self.window.end > self.as_of or self.window.end > self.available_at: raise ValueError('WINDOW_NOT_FINISHED')
        require_input_refs(self,(self.research_run_ref,self.plan_ref,self.quality_ref,*self.observation_refs,
            *([self.entry_quote_ref] if self.entry_quote_ref else []),*([self.exit_quote_ref] if self.exit_quote_ref else [])))
        if self.reference_return is not None and (self.entry_quote_ref is None or self.exit_quote_ref is None): raise ValueError('RETURN_QUOTES')
        if self.simulation.cost_plan_ref!=self.plan_ref: raise ValueError('SIMULATION_PLAN')
        if (self.mfe is None)!=(self.mae is None) or (self.mfe is not None and self.mfe<self.mae): raise ValueError('DIAGNOSTIC_RANGE')
        return self


class GroupStatistic(Contract):
    group: Text
    window: WindowName
    total_frozen: Count
    settled: Count
    partially_settled: Count
    unsettled: Count
    data_hold: Count
    execution_hold: Count
    pit_hold: Count
    sample_n: Count
    event_cluster_n: Count
    settled_event_cluster_n: Count
    unresolved_event_sample_n: Count
    repeated_security_path_count: Count
    coverage_rate: float | None
    settlement_rate: float | None
    positive_return_rate: float | None
    negative_return_rate: float | None
    mean_return: float | None
    median_return: float | None
    simulated_mean_return: float | None
    mfe: float | None
    mae: float | None
    cluster_mean_return: float | None
    interval: Items[float] | None
    interval_estimand: Literal['EQUAL_EVENT_CLUSTER_MEAN_REFERENCE_RETURN'] = 'EQUAL_EVENT_CLUSTER_MEAN_REFERENCE_RETURN'
    conclusion: Literal['NO_EDGE_OBSERVED','NEGATIVE_EDGE','INCONCLUSIVE','INSUFFICIENT_SAMPLE','DATA_QUALITY_HOLD']
    hold_reasons: Items[Text]

    @model_validator(mode='after')
    def counts(self):
        if sum((self.settled,self.partially_settled,self.unsettled,self.data_hold,self.execution_hold,self.pit_hold))!=self.total_frozen:
            raise ValueError('REPORT_DENOMINATOR')
        if self.sample_n>self.total_frozen or self.event_cluster_n>self.total_frozen or self.settled_event_cluster_n>self.event_cluster_n:
            raise ValueError('REPORT_COUNTS')
        if self.total_frozen==0:
            if self.coverage_rate is not None or self.settlement_rate is not None: raise ValueError('REPORT_EMPTY_RATE')
        elif (self.coverage_rate is None or self.settlement_rate is None
            or abs(self.coverage_rate-self.sample_n/self.total_frozen)>1e-9
            or abs(self.settlement_rate-self.settled/self.total_frozen)>1e-9): raise ValueError('REPORT_COVERAGE_RATE')
        return self


class EvaluationIncident(EvaluationEnvelope):
    research_run_ref: VersionRef
    category: Literal['PIT_VIOLATION']
    diagnostic_code: Text


class ForwardHealth(Contract):
    runs_expected: Count
    runs_created: Count
    runs_settled: Count
    runs_late: Count
    candidate_total: Count
    outcome_total: Count
    quote_coverage: float | None
    calendar_coverage: float | None
    settlement_coverage: float | None
    stale_data_count: Count
    missing_data_count: Count
    execution_hold_count: Count
    empty_list_rate: float | None
    pit_violation_count: Count
    health: Literal['ENGINEERING_ONLY','HOLD']

    @model_validator(mode='after')
    def pit(self):
        if self.pit_violation_count and self.health!='HOLD': raise ValueError('FORWARD_PIT_HOLD')
        return self


class EvaluationReport(EvaluationEnvelope):
    research_run_refs: Items[VersionRef]
    evaluation_plan_ref: VersionRef
    outcome_refs: Items[VersionRef]
    epoch: Text
    report_kind: Literal['ENGINEERING_REPORT','MOCK_FORWARD_REPORT','PUBLIC_PIT_REPORT','HISTORICAL_RECOMPUTE','REAL_FORWARD_REPORT']
    statistics: Items[GroupStatistic]
    health: ForwardHealth
    hold_reasons: Items[Text]
    notices: Items[Text] = ('ENGINEERING_DEMO','NO_ALPHA_CLAIM','NO_INVESTMENT_ADVICE','SIMULATED_ONLY')

    @model_validator(mode='after')
    def inputs(self):
        require_input_refs(self,(*self.research_run_refs,self.evaluation_plan_ref,*self.outcome_refs))
        return self


SCHEMAS = {c.__name__: c for c in (SettlementCalendar,EvaluationPlan,FrozenFeatureArchive,ResearchRunManifest,
    OutcomeQuote,Outcome,SampleQuality,EvaluationIncident,EvaluationReport)}
