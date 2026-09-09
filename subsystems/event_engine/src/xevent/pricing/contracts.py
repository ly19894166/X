"""Phase8领域契约；无价格预测、账户字段或交易指令。"""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from ..contracts.common import Contract, DerivedEnvelope, Items, Text, UTCDateTime, VersionRef, Band, Count, Ratio
from ..ontology.contracts import Chinese, Currency, CurrencyPair, Target

POLICY='X_PRICING_V0.1'
PricingMode=Literal['ENGINEERING_FIXTURE','MOCK_FORWARD','HISTORICAL_REPLAY','REAL_FORWARD']
Quality=Literal['QUALIFIED','DEGRADED','STALE','UNKNOWN','HOLD']
ObservationType=Literal['PRICE','RETURN','VOLUME','TURNOVER','AMOUNT','VWAP','VOLATILITY','BREADTH',
    'INDUSTRY_RETURN','BENCHMARK_RETURN','CROSS_ASSET']
Unit=Literal['CURRENCY_PER_UNIT','INDEX_POINT','SHARE','CURRENCY','RATIO','FX_RATE','UNKNOWN']
Recognition=Literal['UNRECOGNIZED','EARLY_RECOGNITION','PARTIAL_RECOGNITION','BROAD_RECOGNITION','CONSENSUS','UNKNOWN']
PriceIn=Literal['LOW','MEDIUM','HIGH','VERY_HIGH','UNKNOWN','HOLD']
Risk=Literal['LOW','MEDIUM','HIGH','EXTREME','UNKNOWN']
Edge=Literal['STRONG','POSITIVE','THIN','NONE','NEGATIVE','UNKNOWN','HOLD']
BuyerType=Literal['EVENT_DISCOVERY','INDUSTRY_DIFFUSION','FUNDAMENTAL_REVALUATION','TREND_FOLLOWING',
    'CROSS_ASSET_TRANSMISSION','EARNINGS_REPRICING','SUPPLY_CHAIN_DIFFUSION','THEME_ROTATION','SHORT_COVERING','UNKNOWN']
CAUSES=('OTHER_EVENT','EARNINGS','ORDER','MERGER','POLICY','SECTOR_RALLY','COMMODITY','INDEX_BETA',
        'OTHER_THEME','TECHNICAL_REBOUND','PRIOR_EVENT')
NONREACTION=('OLD_NEWS','WRONG_EXPOSURE','IMMATERIAL','MACRO_PRESSURE','COMPANY_COUNTERFACTOR',
    'ILLIQUID','DATA_DELAY','WRONG_EVENT_TIME','PRE_EVENT_TRADING','COUNTEREVIDENCE','INDIRECT_BENEFIT','LONG_HORIZON')
FindingCode=Literal['DISSEMINATION','REMAINING_DIFFUSION','OTHER_EVENT','EARNINGS','ORDER','MERGER','POLICY',
    'SECTOR_RALLY','COMMODITY','INDEX_BETA','OTHER_THEME','TECHNICAL_REBOUND','PRIOR_EVENT',
    'OLD_NEWS','WRONG_EXPOSURE','IMMATERIAL','MACRO_PRESSURE','COMPANY_COUNTERFACTOR','ILLIQUID',
    'DATA_DELAY','WRONG_EVENT_TIME','PRE_EVENT_TRADING','COUNTEREVIDENCE','INDIRECT_BENEFIT','LONG_HORIZON']


class Window(Contract):
    start: UTCDateTime
    end: UTCDateTime
    @model_validator(mode='after')
    def ordered(self):
        if self.end<self.start: raise ValueError('MARKET_WINDOW：结束不得早于开始')
        return self


class PricingEnvelope(DerivedEnvelope):
    as_of: UTCDateTime
    observed_at: UTCDateTime
    pricing_mode: PricingMode
    provenance_zh: Chinese
    @model_validator(mode='after')
    def times(self):
        if not self.observed_at<=self.as_of<=self.computed_at:
            raise ValueError('PRICING_PIT：观察及知识截止必须先于实际完成')
        return self
    def is_visible(self,query):
        if query.mode=='LIVE_FORWARD' and self.pricing_mode!='REAL_FORWARD': return False
        return super().is_visible(query)


class MarketInstrument(PricingEnvelope):
    canonical_name_zh: Chinese
    target_object: Target | None = None
    asset_type: Literal['INDEX','COMMODITY','FX','OVERSEAS_PEER','RATE']
    currency: Currency
    timezone: Text
    fx_pair: CurrencyPair | None = None
    @model_validator(mode='after')
    def instrument(self):
        if self.asset_type=='COMMODITY' and self.target_object is None: raise ValueError('COMMODITY_TARGET_REQUIRED')
        if (self.asset_type=='FX')!=(self.fx_pair is not None):
            raise ValueError('FX_PAIR：汇率必须明确base/quote，其他资产不得伪装汇率')
        if self.fx_pair and self.currency!=self.fx_pair.quote: raise ValueError('FX_QUOTE')
        return self


class MarketSession(PricingEnvelope):
    instrument_ref: VersionRef
    source_ref: VersionRef
    timezone: Text
    utc_offset_minutes: Annotated[int,Field(ge=-840,le=840)]
    timezone_basis: Literal["PROVIDER_DECLARED_SESSION_OFFSET"]="PROVIDER_DECLARED_SESSION_OFFSET"
    intervals: Items[Window]
    calendar_version: Text
    @model_validator(mode='after')
    def schedule(self):
        if any(w.start==w.end for w in self.intervals) or any(a.end>b.start for a,b in zip(self.intervals,self.intervals[1:])):
            raise ValueError('CALENDAR_INTERVAL：交易区间必须有序且不重叠')
        return self


class AdjustmentBasis(PricingEnvelope):
    instrument_ref: VersionRef
    adjustment_type: Literal['UNADJUSTED','PIT_ADJUSTED']
    factor: Annotated[float,Field(gt=0)]
    source_ref: VersionRef
    @model_validator(mode='after')
    def factor_gate(self):
        if self.adjustment_type=='UNADJUSTED' and self.factor!=1.0: raise ValueError('ADJUSTMENT_UNIT')
        return self


class ProviderQualification(PricingEnvelope):
    provider: Text
    source_ref: VersionRef
    qualification_status: Literal['PROVIDER_QUALIFIED','PROVIDER_DEGRADED','PROVIDER_HOLD']
    scope: Literal['ENGINEERING_FIXTURE_ONLY']='ENGINEERING_FIXTURE_ONLY'
    timestamp_verified: bool
    unit_verified: bool
    currency_verified: bool
    qualification_evidence_zh: Chinese
    @model_validator(mode='after')
    def qualified(self):
        if self.qualification_status=='PROVIDER_QUALIFIED' and not all((self.timestamp_verified,self.unit_verified,self.currency_verified)):
            raise ValueError('PROVIDER_QUALIFICATION：时间、单位与币种必须分别核验')
        if self.pricing_mode=='REAL_FORWARD': raise ValueError('HOLD_MARKET_DATA_PROVIDER_LIVE')
        return self


class MarketObservation(PricingEnvelope):
    instrument_ref: VersionRef
    observation_type: ObservationType
    window: Window
    value: float | None
    missing_reason: Text | None = None
    unit: Unit
    currency: Currency | None
    adjustment_ref: VersionRef
    adjustment_type: Literal['UNADJUSTED','PIT_ADJUSTED']
    source_ref: VersionRef
    provider_ref: VersionRef
    provider: Text
    provider_timestamp: UTCDateTime
    received_at: UTCDateTime
    first_seen_at: UTCDateTime
    session_ref: VersionRef
    staleness_seconds: Annotated[float,Field(ge=0)]
    quality_status: Quality
    component_price_refs: Items[VersionRef] = ()
    @model_validator(mode='after')
    def observation(self):
        if not self.window.end<=self.observed_at<=self.provider_timestamp<=self.received_at<=self.as_of:
            raise ValueError('MARKET_TIME：窗口/观察/来源/接收/可知时间倒置')
        if self.first_seen_at>self.received_at: raise ValueError('MARKET_FIRST_SEEN')
        if abs(self.staleness_seconds-(self.received_at-self.observed_at).total_seconds())>1e-6:
            raise ValueError('MARKET_STALENESS')
        if self.value is None and not self.missing_reason: raise ValueError('MARKET_UNKNOWN：未知数值需null及原因')
        if self.quality_status=='QUALIFIED' and self.value is None: raise ValueError('MARKET_QUALITY')
        if self.value is not None:
            if self.observation_type in ('PRICE','VWAP','CROSS_ASSET') and self.value<=0: raise ValueError('PRICE_POSITIVE')
            if self.observation_type in ('VOLUME','AMOUNT','TURNOVER','VOLATILITY','BREADTH') and self.value<0: raise ValueError('MARKET_NONNEGATIVE')
            if self.observation_type in ('TURNOVER','BREADTH') and self.value>1: raise ValueError('MARKET_RATIO')
        if self.observation_type=='PRICE' and self.window.start!=self.window.end: raise ValueError('PRICE_POINT_REQUIRED')
        expected={'VOLUME':{'SHARE'},'AMOUNT':{'CURRENCY'},'TURNOVER':{'RATIO'},'BREADTH':{'RATIO'},
            'RETURN':{'RATIO'},'INDUSTRY_RETURN':{'RATIO'},'BENCHMARK_RETURN':{'RATIO'},'VOLATILITY':{'RATIO'},
            'PRICE':{'CURRENCY_PER_UNIT','INDEX_POINT'},'VWAP':{'CURRENCY_PER_UNIT'},
            'CROSS_ASSET':{'CURRENCY_PER_UNIT','INDEX_POINT','FX_RATE'}}
        if self.unit not in expected[self.observation_type] and self.quality_status not in ('UNKNOWN','HOLD'):
            raise ValueError('MARKET_UNIT：系统性单位错误')
        return self


class BenchmarkComposition(PricingEnvelope):
    benchmark_ref: VersionRef
    component_security_refs: Items[VersionRef]
    expected_component_count: Count
    source_ref: VersionRef
    industry_ref: VersionRef | None = None
    coverage_status: Literal['COMPLETE_DECLARED_SCOPE','INCOMPLETE']
    @model_validator(mode='after')
    def denominator(self):
        n=len(set(self.component_security_refs))
        if n!=len(self.component_security_refs) or self.expected_component_count<n:
            raise ValueError('BENCHMARK_COMPONENTS')
        if self.coverage_status=='COMPLETE_DECLARED_SCOPE' and (n==0 or n!=self.expected_component_count):
            raise ValueError('BENCHMARK_DENOMINATOR')
        return self


class BenchmarkSnapshot(PricingEnvelope):
    benchmark_ref: VersionRef
    benchmark_role: Literal['MARKET','INDUSTRY','STYLE','THEME']
    composition_ref: VersionRef
    price_refs: Items[VersionRef]
    window: Window
    return_value: float | None
    adjustment_ref: VersionRef
    source_ref: VersionRef
    quality_status: Quality
    method: Literal['END_OVER_START_MINUS_ONE']='END_OVER_START_MINUS_ONE'


class Finding(Contract):
    dimension: FindingCode
    outcome: Literal['YES','NO','UNKNOWN']
    evidence_ref: VersionRef | None = None
    quoted_span: Text | None = None
    interpretation_zh: Chinese
    reviewed_by: Text | None = None
    @model_validator(mode='after')
    def evidence(self):
        if self.outcome!='UNKNOWN' and (not self.evidence_ref or not self.quoted_span or not self.reviewed_by):
            raise ValueError('FINDING_PROOF：已审阅判断需固定原文及核验者；不是因果证明')
        return self


class PricingContext(PricingEnvelope):
    event_ref: VersionRef
    security_ref: VersionRef
    findings: Items[Finding]
    @model_validator(mode='after')
    def unique(self):
        if len({f.dimension for f in self.findings})!=len(self.findings): raise ValueError('FINDING_DUPLICATE')
        return self


class NextBuyerSpec(Contract):
    buyer_type: BuyerType
    supporting_observation_refs: Items[VersionRef]
    supporting_path_refs: Items[VersionRef]
    why_not_already_present: Chinese | None
    expected_trigger: Chinese | None
    failure_condition: Chinese | None
    confidence_band: Band
    non_presence_evidence_ref: VersionRef | None = None
    quoted_span: Text | None = None


class NextBuyerHypothesis(PricingEnvelope,NextBuyerSpec):
    hypothesis_status: Literal['SUPPORTED','PLAUSIBLE','WEAK','UNKNOWN','REJECTED']
    reason_codes_buyer: Items[Text]
    epistemic_status: Literal['HYPOTHESIS_NOT_OBSERVED_BUYER']='HYPOTHESIS_NOT_OBSERVED_BUYER'


class MissingItem(Contract):
    dimension: Text
    reason: Chinese
    severity: Literal['INFO','DEGRADED','BLOCKING']
    required_for_formal_pricing: bool
    source_status: Text


class MissingDimensions(PricingEnvelope):
    items: Items[MissingItem]


class EventAnchor(Contract):
    event_ref: VersionRef
    public_time: UTCDateTime | None
    first_seen_time: UTCDateTime
    known_at: UTCDateTime
    proof_refs: Items[VersionRef]
    method: Literal['SYSTEM_VERSION_AVAILABLE']='SYSTEM_VERSION_AVAILABLE'


class DiffusionFeatures(Contract):
    eligible_company_count: Count
    reacting_company_count: Count | None
    observed_company_count: Count
    breadth_ratio: Ratio | None
    median_relative_return: float | None
    dispersion: float | None
    leader_concentration: Ratio | None
    denominator_source: VersionRef
    coverage: Literal['COMPLETE_DECLARED_SCOPE','INCOMPLETE']


class MarketReactionFeatures(PricingEnvelope):
    security_ref: VersionRef
    anchor: EventAnchor
    reaction_window: Window
    pre_event_window: Window | None
    observation_refs: Items[VersionRef]
    benchmark_refs: Items[VersionRef]
    raw_return: float | None
    market_relative_return: float | None
    industry_relative_return: float | None
    pre_event_return: float | None
    volume_ratio: float | None
    amount_ratio: float | None
    volume_sample_n: Count
    amount_sample_n: Count
    diffusion: DiffusionFeatures | None
    method: Literal['SIMPLE_RELATIVE_RETURN_NOT_CAUSAL']='SIMPLE_RELATIVE_RETURN_NOT_CAUSAL'
    beta: None = None
    beta_method: Literal['NOT_ESTIMATED']='NOT_ESTIMATED'
    traded_session_count: Count
    turnover: float | None = None
    volatility: float | None = None
    breadth_delta: float | None = None
    cross_asset_state: Literal['NOT_APPLICABLE','SYNCHRONOUS_CONTEXT','ASYNCHRONOUS','UNKNOWN']
    converted_currency: Currency | None = None
    converted_unit: Unit | None = None
    converted_cross_asset_value: float | None = None
    conversion_basis: Text | None = None


class NonReactionInvestigation(PricingEnvelope):
    checks: Items[Finding]
    investigation_status: Literal['EXPLAINED_NON_REACTION','UNEXPLAINED_NON_REACTION','DATA_INSUFFICIENT','HOLD']
    triggered: bool
    recognition_gap: bool
    basis_refs: Items[VersionRef]


class AlternativeCauseSearch(PricingEnvelope):
    checks: Items[Finding]
    cause_status: Literal['CURRENT_EVENT_DOMINANT','MULTI_CAUSE','ALTERNATIVE_CAUSE_STRONG','CAUSE_UNKNOWN']
    search_scope: Literal['FIXED_PIT_INPUTS_NOT_EXHAUSTIVE']='FIXED_PIT_INPUTS_NOT_EXHAUSTIVE'
    reason_codes_cause: Items[Text]
    basis_refs: Items[VersionRef]


class PricingRules(Contract):
    low_reaction: Annotated[float,Field(gt=0)]=0.005
    noticeable_relative: Annotated[float,Field(gt=0)]=0.01
    large_relative: Annotated[float,Field(gt=0)]=0.05
    abnormal_volume: Annotated[float,Field(gt=1)]=2.0
    extreme_volume: Annotated[float,Field(gt=1)]=4.0
    broad_diffusion: Ratio=0.6
    consensus_diffusion: Ratio=0.85
    min_volume_samples: Annotated[int,Field(ge=2)]=3
    sustained_sessions: Annotated[int,Field(ge=2)]=3
    max_price_age_seconds: Annotated[int,Field(gt=0)]=300
    @model_validator(mode='after')
    def order(self):
        if not self.low_reaction<self.noticeable_relative<self.large_relative or self.abnormal_volume>=self.extreme_volume or self.broad_diffusion>=self.consensus_diffusion:
            raise ValueError('PRICING_POLICY_THRESHOLDS')
        return self


class PricingPolicy(PricingEnvelope):
    rules: PricingRules
    calibration_status: Literal['ENGINEERING_UNCALIBRATED']='ENGINEERING_UNCALIBRATED'


class PricingRequest(Contract):
    analysis_ref: VersionRef
    security_ref: VersionRef
    path_ref: VersionRef
    policy_ref: VersionRef
    as_of: UTCDateTime
    pricing_mode: PricingMode
    reaction_window: Window
    price_refs: Items[VersionRef] = ()
    pre_price_refs: Items[VersionRef] = ()
    benchmark_refs: Items[VersionRef] = ()
    volume_ref: VersionRef | None = None
    amount_ref: VersionRef | None = None
    volume_baseline_refs: Items[VersionRef] = ()
    amount_baseline_refs: Items[VersionRef] = ()
    diffusion_price_refs: Items[VersionRef] = ()
    prior_session_price_refs: Items[VersionRef] = ()
    volatility_ref: VersionRef | None = None
    turnover_ref: VersionRef | None = None
    previous_features_ref: VersionRef | None = None
    context_ref: VersionRef | None = None
    next_buyers: Items[NextBuyerSpec] = ()
    cross_asset_ref: VersionRef | None = None
    fx_ref: VersionRef | None = None


class PricingAssessment(PricingEnvelope):
    request: PricingRequest
    event_ref: VersionRef
    security_ref: VersionRef
    research_refs: Items[VersionRef]
    market_observation_refs: Items[VersionRef]
    benchmark_refs: Items[VersionRef]
    features_ref: VersionRef
    recognition_state: Recognition
    price_in_band: PriceIn
    crowding_band: Risk
    remaining_edge: Edge
    reversal_risk: Risk
    next_buyer_refs: Items[VersionRef]
    non_reaction_ref: VersionRef
    alternative_cause_ref: VersionRef
    missing_dimensions_ref: VersionRef
    dimension_reasons: dict[str,Items[Text]]
    thesis_strength: Band
    novelty: Literal['R0','R1','R2','R3','R4','R5','UNDETERMINED']
    assessment_status: Literal['ENGINEERING_ONLY','HOLD']
    formal_positive_remaining_edge: Literal[False]=False
    hold_reasons: Items[Text]
    @model_validator(mode='after')
    def output(self):
        if self.request.as_of!=self.as_of or self.request.pricing_mode!=self.pricing_mode: raise ValueError('PRICING_REQUEST')
        if self.assessment_status=='HOLD' and (self.price_in_band not in ('UNKNOWN','HOLD') or self.remaining_edge not in ('UNKNOWN','HOLD')):
            raise ValueError('PRICING_HOLD：阻塞数据或上游不能发布正向空间')
        return self


SCHEMAS={c.__name__:c for c in (MarketInstrument,MarketSession,AdjustmentBasis,ProviderQualification,MarketObservation,
    BenchmarkComposition,BenchmarkSnapshot,PricingContext,NextBuyerHypothesis,MissingDimensions,MarketReactionFeatures,
    NonReactionInvestigation,AlternativeCauseSearch,PricingPolicy,PricingAssessment)}