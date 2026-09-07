"""Phase 5：稳定经济实体、证券与知识版本；所有引用固定版本。"""
from datetime import date, datetime
from typing import Annotated, Literal
from pydantic import BeforeValidator, Field, model_validator
from ..contracts.common import Contract, DerivedEnvelope, Items, Text, UTCDateTime, VersionRef, Count
from ..contracts.models import identity_matches, require_input_refs

def calendar_day(value):
    if isinstance(value, datetime) or not isinstance(value,(str,date)):
        raise ValueError("CALENDAR_DATE：必须YYYY-MM-DD或date，禁止数值时间戳/datetime")
    if isinstance(value,str) and (len(value)!=10 or value[4]!="-" or value[7]!="-"):
        raise ValueError("CALENDAR_DATE：日期必须YYYY-MM-DD")
    return value


Day = Annotated[date, Field(strict=False), BeforeValidator(calendar_day)]
IdentityStatus = Literal["VERIFIED", "UNKNOWN", "HOLD", "REVIEW_REQUIRED"]
POLICY = "X_PHASE5_V0.1"
UNIVERSE = "ALL_A_SHARE_RESEARCH_V0.1"


class Provenance(Contract):
    evidence_refs: Items[VersionRef]
    source_refs: Items[VersionRef]
    provenance_zh: Text
    reviewed_by: Text | None = None

    @model_validator(mode="after")
    def proof(self):
        if not self.evidence_refs or not self.source_refs:
            raise ValueError("PROVENANCE：必须提供证据与来源的固定版本")
        return self


class EffectiveSpec(Provenance):
    effective_from: UTCDateTime
    effective_to: UTCDateTime | None = None

    @model_validator(mode="after")
    def interval(self):
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("EFFECTIVE_INTERVAL：结束必须晚于开始")
        return self


class CompanySpec(EffectiveSpec):
    company_id: Text
    canonical_name_zh: Text
    legal_name: Text
    company_identifier: Text | None = None
    domicile: Text
    operating_geographies: Items[Text] = ()
    company_status: Literal["ACTIVE", "DISSOLVED", "RESTRUCTURING", "UNKNOWN"]
    identity_status: IdentityStatus = "UNKNOWN"
    identity_reason_zh: Text
    continuity_status: Literal["CONFIRMED", "REVIEW_REQUIRED"] = "REVIEW_REQUIRED"

    @model_validator(mode="after")
    def continuity(self):
        if self.identity_status == "VERIFIED" and (self.continuity_status != "CONFIRMED" or not self.reviewed_by):
            raise ValueError("COMPANY_IDENTITY：法律身份连续性未确认，只能HOLD/REVIEW_REQUIRED")
        return self


class SecuritySpec(EffectiveSpec):
    security_id: Text
    company_ref: VersionRef
    exchange: Literal["SSE", "SZSE", "BSE", "HKEX", "OTHER", "UNKNOWN"]
    security_code: Text
    ticker: Text
    security_name: Text
    security_type: Literal["A_SHARE", "H_SHARE", "OTHER", "UNKNOWN"]
    board: Literal["SH_MAIN", "SZ_MAIN", "CHINEXT", "STAR", "BEIJING", "HK", "OTHER", "UNKNOWN"]
    currency: Text
    listing_status: Literal["LISTED", "DELISTED", "NOT_LISTED", "UNKNOWN"]
    st_status: Literal["NORMAL", "ST", "*ST", "UNKNOWN"]
    suspension_status: Literal["TRADING", "SUSPENDED", "UNKNOWN"]
    listing_date: Day | None = None
    delisting_date: Day | None = None
    identity_status: IdentityStatus = "UNKNOWN"
    identity_reason_zh: Text

    @model_validator(mode="after")
    def security_gate(self):
        if self.security_type == "A_SHARE":
            expected = {"SH_MAIN": "SSE", "STAR": "SSE", "SZ_MAIN": "SZSE", "CHINEXT": "SZSE", "BEIJING": "BSE"}
            if len(self.security_code) != 6 or not self.security_code.isascii() or not self.security_code.isdigit():
                raise ValueError("SECURITY_CODE：A股必须六位字符串，禁止数值化")
            if expected.get(self.board) != self.exchange or self.currency != "CNY":
                raise ValueError("SECURITY_CLASSIFICATION：A股板块/交易所/币种不一致")
        if self.delisting_date and self.listing_date and self.delisting_date < self.listing_date:
            raise ValueError("LISTING_DATE：退市不得早于上市")
        if self.identity_status == "VERIFIED" and not self.reviewed_by:
            raise ValueError("SECURITY_IDENTITY：核实身份需要核验者")
        if self.listing_status == "DELISTED" and self.delisting_date is None:
            raise ValueError("DELISTING_DATE：退市状态必须提供日期")
        return self


class RelationSpec(EffectiveSpec):
    relation_id: Text
    company_ref: VersionRef
    security_ref: VersionRef
    identity_status: IdentityStatus = "UNKNOWN"
    identity_reason_zh: Text


class RegistryEnvelope(DerivedEnvelope):
    @model_validator(mode="after")
    def references(self):
        refs = list(getattr(self, "source_refs", ()))
        for name in ("company_ref", "security_ref"):
            if getattr(self, name, None):
                refs.append(getattr(self, name))
        require_input_refs(self, refs)
        return self


class Company(CompanySpec, RegistryEnvelope):
    @model_validator(mode="after")
    def identity(self):
        identity_matches(self, "company_id")
        return self


class SecurityVersion(SecuritySpec, RegistryEnvelope):
    @model_validator(mode="after")
    def identity(self):
        identity_matches(self, "security_id")
        return self


class CompanySecurityRelation(RelationSpec, RegistryEnvelope):
    @model_validator(mode="after")
    def identity(self):
        identity_matches(self, "relation_id")
        return self


class UniverseDecision(Contract):
    security_ref: VersionRef
    company_ref: VersionRef | None = None
    relation_ref: VersionRef | None = None
    decision: Literal["INCLUDED", "EXCLUDED", "HOLD"]
    reason_codes: Items[Text]


class ResearchUniverseSnapshot(DerivedEnvelope):
    snapshot_id: Text
    as_of: UTCDateTime
    universe_definition_version: Literal["ALL_A_SHARE_RESEARCH_V0.1"] = UNIVERSE
    included_security_refs: Items[VersionRef]
    excluded_security_refs: Items[VersionRef]
    security_hold_refs: Items[VersionRef]
    source_refs: Items[VersionRef]
    decisions: Items[UniverseDecision]
    coverage_status: Literal["HOLD_HISTORICAL_UNIVERSE_COVERAGE"] = "HOLD_HISTORICAL_UNIVERSE_COVERAGE"
    capability: Literal["ENGINE SUPPORTS FULL-A-SHARE RESEARCH UNIVERSE"] = "ENGINE SUPPORTS FULL-A-SHARE RESEARCH UNIVERSE"

    @model_validator(mode="after")
    def snapshot_gate(self):
        identity_matches(self, "snapshot_id")
        require_input_refs(self, (*self.included_security_refs, *self.excluded_security_refs, *self.security_hold_refs, *self.source_refs,
            *(r for d in self.decisions for r in (d.company_ref, d.relation_ref) if r)))
        if self.as_of > self.computed_at or any(r.available_at > self.as_of for r in self.input_version_refs):
            raise ValueError("PIT_UNIVERSE：分母不得使用截止点之后的身份/来源")
        groups = {"INCLUDED": self.included_security_refs, "EXCLUDED": self.excluded_security_refs, "HOLD": self.security_hold_refs}
        keys = [(d.security_ref.object_id, d.security_ref.version) for d in self.decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("UNIVERSE_DUPLICATE：证券决策不能重复")
        for status, refs in groups.items():
            if tuple(d.security_ref for d in self.decisions if d.decision == status) != refs:
                raise ValueError("UNIVERSE_DECISION：分组与逐项决策不一致")
        return self


SCHEMAS = {c.__name__: c for c in (Company, SecurityVersion, CompanySecurityRelation, ResearchUniverseSnapshot)}
