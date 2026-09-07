"""披露、暴露和独立指标：现实期间不等于知识时间。"""
from typing import Literal
from pydantic import model_validator
from ..contracts.common import Contract, DerivedEnvelope, Items, Text, UTCDateTime, VersionRef, Count
from ..contracts.models import identity_matches, require_input_refs
from ..registry.contracts import Day, EffectiveSpec, RegistryEnvelope, Provenance

DisclosureType = Literal["ANNUAL_REPORT", "HALF_YEAR_REPORT", "ANNOUNCEMENT", "PROSPECTUS",
    "OFFICIAL_COMPANY_DISCLOSURE", "VERIFIED_REGULATORY_DOCUMENT", "NEWS", "NARRATIVE", "UNKNOWN"]
DIRECT_TYPES = {"ANNUAL_REPORT","HALF_YEAR_REPORT","ANNOUNCEMENT","PROSPECTUS","OFFICIAL_COMPANY_DISCLOSURE","VERIFIED_REGULATORY_DOCUMENT"}
ExposureType = Literal["VERIFIED_DIRECT","SUPPORTED_DIRECT","INFERRED","NARRATIVE_ASSOCIATION","UNKNOWN","HOLD"]
BusinessRole = Literal["PRODUCER","PROCESSOR","MANUFACTURER","SUPPLIER","CUSTOMER","INPUT_USER",
    "DISTRIBUTOR","SERVICE_PROVIDER","SUBSTITUTE","MIXED","UNKNOWN"]
MetricType = Literal["REVENUE","REVENUE_SHARE","GROSS_PROFIT","GROSS_PROFIT_SHARE","OPERATING_PROFIT",
    "PROFIT_SHARE","CAPACITY","CAPACITY_SHARE","PRODUCTION","SALES_VOLUME","ORDER_VALUE","CUSTOMER_SHARE","ASSET_VALUE","UNKNOWN"]
ValidationStatus = Literal["VERIFIED","SUPPORTED","UNREVIEWED","CANDIDATE_FOR_REVIEW","UNKNOWN","HOLD","UNDEFINED"]
SHARES = {"REVENUE_SHARE","GROSS_PROFIT_SHARE","PROFIT_SHARE","CAPACITY_SHARE","CUSTOMER_SHARE"}


class ReportingPeriod(Contract):
    start: Day
    end: Day
    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("REPORTING_PERIOD：报告期结束不能早于开始")
        return self


class DisclosureSpec(Provenance):
    disclosure_id: Text
    company_ref: VersionRef
    reporting_period: ReportingPeriod
    disclosure_type: DisclosureType
    published_at: UTCDateTime | None
    first_seen_at: UTCDateTime
    review_status: Literal["MANUALLY_VERIFIED", "UNREVIEWED", "HOLD"]
    quoted_span: Text
    issuer_identity_verified: bool = False
    revision_reason_zh: Text
    input_method: Literal["FIXTURE", "MANUAL_STRUCTURED"] = "MANUAL_STRUCTURED"

    @model_validator(mode="after")
    def reviewer(self):
        if self.review_status == "MANUALLY_VERIFIED" and not self.reviewed_by:
            raise ValueError("DISCLOSURE_REVIEW：正式人工核验必须记录核验者")
        return self


class DisclosureImport(DisclosureSpec, RegistryEnvelope):
    @model_validator(mode="after")
    def identity_time(self):
        identity_matches(self, "disclosure_id")
        if self.first_seen_at > self.available_at or (self.published_at and self.published_at > self.available_at):
            raise ValueError("PIT_DISCLOSURE：披露尚未公开或接收")
        return self


class ExposureSpec(EffectiveSpec):
    exposure_id: Text
    company_ref: VersionRef
    industry_ref: VersionRef | None
    business_role: BusinessRole
    exposure_type: ExposureType
    geography: Items[Text]
    reporting_period: ReportingPeriod
    evidence_type: DisclosureType
    source_disclosure_ref: VersionRef
    validation_status: ValidationStatus
    mechanism_zh: Text
    description_zh: Text
    mapping_method: Literal["MANUAL_VERIFIED", "EXACT_ALIAS_REVIEWED", "VERIFIED_RULE", "KEYWORD_CANDIDATE", "UNKNOWN"]
    mapping_review_zh: Text
    narrative_theme_ref: VersionRef | None = None

    @model_validator(mode="after")
    def exposure_gate(self):
        if self.exposure_type == "VERIFIED_DIRECT" and (
            self.evidence_type not in DIRECT_TYPES or self.validation_status != "VERIFIED" or
            self.mapping_method not in ("MANUAL_VERIFIED","EXACT_ALIAS_REVIEWED","VERIFIED_RULE") or not self.reviewed_by):
            raise ValueError("DIRECT_PROOF：直接核实暴露需要正式披露及明确业务映射核验")
        if self.exposure_type in ("VERIFIED_DIRECT","SUPPORTED_DIRECT","INFERRED") and self.industry_ref is None:
            raise ValueError("EXPOSURE_INDUSTRY：经济暴露必须固定产业版本；未知产业保留UNKNOWN")
        if self.narrative_theme_ref is not None and self.exposure_type != "NARRATIVE_ASSOCIATION":
            raise ValueError("NARRATIVE_GATE：主题不能升级真实业务暴露")
        if self.exposure_type == "NARRATIVE_ASSOCIATION" and self.industry_ref is not None:
            raise ValueError("NARRATIVE_GATE：本Phase主题关联不写经济产业暴露")
        if self.mapping_method == "KEYWORD_CANDIDATE" and (
            self.validation_status != "CANDIDATE_FOR_REVIEW" or self.exposure_type not in ("UNKNOWN","HOLD","NARRATIVE_ASSOCIATION")):
            raise ValueError("KEYWORD_GATE：关键词只产生待核验候选")
        if self.exposure_type in ("UNKNOWN","HOLD","NARRATIVE_ASSOCIATION") and self.validation_status == "VERIFIED":
            raise ValueError("EXPOSURE_UNKNOWN：未知/叙事不能冒充核实经济事实")
        return self


class CompanyExposure(ExposureSpec, RegistryEnvelope):
    @model_validator(mode="after")
    def identity_refs(self):
        identity_matches(self, "exposure_id")
        require_input_refs(self, (self.source_disclosure_ref, *([self.industry_ref] if self.industry_ref else []),
            *([self.narrative_theme_ref] if self.narrative_theme_ref else [])))
        return self


class MetricSpec(Contract):
    metric_id: Text
    exposure_ref: VersionRef
    metric_type: MetricType
    numerator: float | None
    denominator: float | None
    unit: Text
    currency: Text | None
    period: ReportingPeriod
    scope: Text
    evidence_ref: VersionRef
    calculation_method: Literal["REPORTED_AMOUNT", "SAME_BASIS_RATIO"]
    validation_status: ValidationStatus
    numerator_basis: Text
    denominator_basis: Text | None
    basis_verified_by: Text | None = None

    @model_validator(mode="after")
    def dimensional_gate(self):
        share = self.metric_type in SHARES
        if share != (self.calculation_method == "SAME_BASIS_RATIO"):
            raise ValueError("METRIC_METHOD：比例与金额/数量算法必须分离")
        if share and self.unit != "RATIO":
            raise ValueError("METRIC_UNIT：比例规范存储为RATIO；不能混入百分数/金额")
        if not share and self.denominator is not None:
            raise ValueError("METRIC_DENOMINATOR：绝对金额/数量不得混入比例分母")
        if self.metric_type in ("REVENUE","GROSS_PROFIT","OPERATING_PROFIT","ORDER_VALUE","ASSET_VALUE") and not self.currency:
            raise ValueError("METRIC_CURRENCY：金额必须声明币种")
        if self.validation_status == "VERIFIED" and not self.basis_verified_by and not share:
            raise ValueError("METRIC_REVIEW：已核实金额/数量需要计量口径核验者")
        return self


def metric_result(spec):
    if spec.metric_type == "UNKNOWN":
        return None, "UNDEFINED", ["METRIC_TYPE_UNKNOWN"]
    if spec.numerator is None:
        return None, "UNDEFINED", ["NUMERATOR_MISSING"]
    if spec.metric_type in SHARES:
        if spec.denominator is None:
            return None, "UNDEFINED", ["DENOMINATOR_MISSING"]
        if spec.denominator <= 0:
            return None, "UNDEFINED", ["DENOMINATOR_ZERO" if spec.denominator == 0 else "DENOMINATOR_NEGATIVE"]
        if spec.numerator < 0:
            return None, "UNDEFINED", ["NEGATIVE_COMPONENT_NOT_A_SHARE"]
        if spec.numerator > spec.denominator:
            return None, "UNDEFINED", ["SHARE_OUT_OF_RANGE"]
        if not spec.denominator_basis or not spec.basis_verified_by:
            return None, "HOLD", ["RATIO_BASIS_UNVERIFIED"]
    if spec.validation_status != "VERIFIED":
        return None, "HOLD", ["METRIC_NOT_VERIFIED"]
    return (spec.numerator / spec.denominator if spec.metric_type in SHARES else spec.numerator), "DEFINED", []


class ExposureMetric(MetricSpec, DerivedEnvelope):
    value: float | None
    result_status: Literal["DEFINED", "UNDEFINED", "HOLD"]
    metric_reason_codes: Items[Text]

    @model_validator(mode="after")
    def metric_gate(self):
        identity_matches(self, "metric_id")
        require_input_refs(self, (self.exposure_ref, self.evidence_ref))
        value, status, reasons = metric_result(self)
        if self.value != value or self.result_status != status or list(self.metric_reason_codes) != reasons:
            raise ValueError("METRIC_RESULT：数值/缺失原因与具名指标算法不一致")
        return self


class CoverageRow(Contract):
    security_ref: VersionRef
    company_ref: VersionRef | None
    relation_ref: VersionRef | None
    board: Text
    exposure_refs: Items[VersionRef]
    economic_exposure_refs: Items[VersionRef]
    exposure_types: Items[ExposureType]
    missing_reason_codes: Items[Text]


class CoverageReport(DerivedEnvelope):
    report_id: Text
    snapshot_ref: VersionRef
    as_of: UTCDateTime
    research_security_n: Count
    identified_company_n: Count
    company_security_mapping_n: Count
    company_with_exposure_n: Count
    company_with_economic_exposure_n: Count
    verified_direct_company_n: Count
    inferred_company_n: Count
    unknown_company_n: Count
    hold_company_n: Count
    security_identity_hold_n: Count
    rows: Items[CoverageRow]
    coverage_status: Literal["HOLD_HISTORICAL_UNIVERSE_COVERAGE"] = "HOLD_HISTORICAL_UNIVERSE_COVERAGE"
    exposure_coverage_status: Literal["HOLD_REAL_COMPANY_EXPOSURE_COVERAGE"] = "HOLD_REAL_COMPANY_EXPOSURE_COVERAGE"

    @model_validator(mode="after")
    def report_refs(self):
        identity_matches(self, "report_id")
        require_input_refs(self, (self.snapshot_ref, *(r for row in self.rows for r in
            (row.security_ref, row.company_ref, row.relation_ref, *row.exposure_refs) if r)))
        if self.research_security_n != len(self.rows):
            raise ValueError("COVERAGE_DENOMINATOR：逐项报告必须覆盖每个研究证券")
        return self


SCHEMAS = {c.__name__:c for c in (DisclosureImport, CompanyExposure, ExposureMetric, CoverageReport)}
