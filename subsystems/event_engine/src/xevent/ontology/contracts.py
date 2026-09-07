"""X产业领域契约；版本/PIT/JSON Schema复用已有Pydantic信封。"""
from typing import Annotated, Literal
from unicodedata import normalize

from pydantic import Field, model_validator

from ..contracts.common import (Band, Contract, Count, DerivedEnvelope, Items,
                                PositiveInt, Text, UTCDateTime, VersionRef)
from ..contracts.models import require_input_refs

Chinese = Annotated[str, Field(min_length=1, pattern=r"[\u3400-\u9fff]", description="必填中文机制或说明")]
IndustryID = Annotated[str, Field(pattern=r"^XIND_[A-Z0-9_]+$")]
VariableType = Literal["DEMAND", "SUPPLY", "PRICE", "INPUT_COST", "ORDER", "CAPEX", "MARKET_SHARE",
    "IMPORT_SUBSTITUTION", "EXPORT_OPPORTUNITY", "SUBSIDY", "REGULATORY_PRESSURE", "FINANCING_COST", "FX", "RISK_PREMIUM"]
Direction = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]
Target = Literal["COPPER", "ELECTRICITY", "AI_COMPUTE", "MANUFACTURING", "CURRENCY"]
Geography = Literal["GLOBAL", "CN", "US", "EU", "JP", "UNKNOWN"]
Currency = Literal["USD", "CNY", "EUR", "JPY", "GBP", "HKD"]
Unit = Literal["TONNE", "CNY_PER_TONNE", "USD_PER_TONNE", "KWH", "COUNT", "PERCENT", "FX_RATE", "UNKNOWN"]
ImpactDirection = Literal["POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"]
StartHorizon = Literal["IMMEDIATE", "MINUTES", "HOURS", "DAYS", "WEEKS", "MONTHS", "UNKNOWN"]
PersistenceBand = Literal["MINUTES", "HOURS", "OVERNIGHT", "ONE_TO_THREE_SESSIONS", "MEDIUM_TERM", "STRUCTURAL", "UNKNOWN"]
PathRole = Literal["PRODUCER", "INPUT_USER", "CUSTOMER", "SUPPLIER", "SUBSTITUTE", "UNRESOLVED"]
MappingStatus = Literal["CANDIDATE", "VERIFIED", "HOLD", "UNRESOLVED"]
EconomicRole = Literal["ROOT", "PRODUCTION", "PROCESSING", "MANUFACTURING", "INFRASTRUCTURE", "SERVICE"]


def phrase_key(text):
    """只作Unicode/空白/大小写规范化；不做模糊匹配或语义猜测。"""
    return " ".join(normalize("NFKC", text).strip().casefold().split())


IMPACT_PHRASES = {phrase_key(p): ("DEMAND", "UP") for p in
    ("DEMAND_INCREASE", "STRONGER_DEMAND", "DEMAND_RISING", "需求增长")}


def normalize_impact_phrase(phrase):
    result = IMPACT_PHRASES.get(phrase_key(phrase))
    return dict(variable_type=result[0], direction=result[1]) if result else None


class CurrencyPair(Contract):
    base: Currency = Field(description="基础币种；一单位base对应多少quote")
    quote: Currency = Field(description="报价币种；USD/CNY UP表示每美元兑换人民币增加")

    @model_validator(mode="after")
    def distinct(self):
        if self.base == self.quote:
            raise ValueError("FX_PAIR：基础币种与报价币种必须不同")
        return self


class ObservationBasis(Contract):
    evidence_ref: VersionRef
    quoted_span: Text
    reviewed_by: Text
    interpretation_zh: Chinese
    scope: Literal["ANNOUNCED_CHANGE", "REPORTED_CHANGE", "MEASURED_CHANGE"]


class ImpactSpec(Contract):
    event_ref: VersionRef
    variable_type: VariableType
    target_object: Target
    direction: Direction
    geography: Geography
    scope: Literal["TARGET_MARKET", "INDUSTRY_ACTIVITY", "ECONOMY", "UNKNOWN"] = "UNKNOWN"
    magnitude_band: Band = "UNKNOWN"
    start_horizon: StartHorizon = "UNKNOWN"
    persistence_band: PersistenceBand = "UNKNOWN"
    unit: Unit = "UNKNOWN"
    currency: Currency | None = None
    fx_pair: CurrencyPair | None = None
    observation_kind: Literal["OBSERVED", "HYPOTHESIS"]
    evidence_refs: Items[VersionRef] = ()
    premise_refs: Items[VersionRef] = ()
    observation_basis: ObservationBasis | None = None
    mechanism_zh: Chinese
    uncertainty_zh: Chinese | None = None
    confidence: Band = "UNKNOWN"
    validation_status: Literal["UNREVIEWED", "VERIFIED", "HOLD"] = "UNREVIEWED"

    @model_validator(mode="after")
    def semantic_boundary(self):
        if self.variable_type == "FX":
            if self.fx_pair is None or self.direction == "UNKNOWN" or self.target_object != "CURRENCY" or self.unit != "FX_RATE":
                raise ValueError("FX_EXPLICIT：FX必须给出base/quote、明确方向、CURRENCY及FX_RATE")
            if self.currency != self.fx_pair.quote:
                raise ValueError("FX_QUOTE：currency必须等于报价币种")
        elif self.fx_pair is not None or self.target_object == "CURRENCY":
            raise ValueError("FX_ONLY：币种对只属于FX变量")
        if self.unit in ("CNY_PER_TONNE", "USD_PER_TONNE") and self.currency != self.unit[:3]:
            raise ValueError("PRICE_UNIT：报价单位与币种不一致")
        if self.observation_kind == "OBSERVED":
            if self.premise_refs or self.observation_basis is None or not self.evidence_refs:
                raise ValueError("OBSERVED_BASIS：观察必须有原文核验，不接受派生premise冒充事实")
            if self.observation_basis.evidence_ref not in self.evidence_refs:
                raise ValueError("OBSERVED_REFERENCE：核验原文须属于本观察证据")
        elif (not self.premise_refs or self.uncertainty_zh is None or self.observation_basis is not None
              or self.validation_status == "VERIFIED"):
            raise ValueError("HYPOTHESIS_BOUNDARY：推断需premise和不确定性，不能冒充已验证观察")
        if self.validation_status == "HOLD" and self.uncertainty_zh is None:
            raise ValueError("IMPACT_HOLD：暂停判断必须说明不确定性")
        return self


class ImpactVariable(DerivedEnvelope, ImpactSpec):
    impact_id: Text

    @model_validator(mode="after")
    def references(self):
        if self.impact_id != self.object_id:
            raise ValueError("IMPACT_ID：impact_id必须等于稳定object_id，修订只追加version")
        require_input_refs(self, (self.event_ref, *self.premise_refs, *self.evidence_refs))
        return self


class SegmentSpec(Contract):
    industry_id: IndustryID
    canonical_name_zh: Chinese
    parent_id: IndustryID | None = None
    level: Count
    economic_role: EconomicRole
    description_zh: Chinese
    effective_from: UTCDateTime
    effective_to: UTCDateTime | None = None


class IndustrySegment(DerivedEnvelope, SegmentSpec):
    ontology_version: Text
    aliases: Items[Text] = ()
    parent_ref: VersionRef | None = None

    @model_validator(mode="after")
    def identity(self):
        if self.object_id != self.industry_id or (self.parent_id is None) != (self.parent_ref is None):
            raise ValueError("INDUSTRY_ID：稳定ID/父版本引用不一致")
        if self.parent_ref:
            if self.parent_ref.object_id != self.parent_id:
                raise ValueError("INDUSTRY_PARENT：父ID与引用不一致")
            require_input_refs(self, (self.parent_ref,))
        return self


class AliasSpec(Contract):
    alias_id: Text
    phrase: Text
    industry_id: IndustryID
    evidence_refs: Items[VersionRef] = ()


class IndustryAlias(DerivedEnvelope, AliasSpec):
    ontology_version: Text
    industry_ref: VersionRef

    @model_validator(mode="after")
    def references(self):
        if self.industry_ref.object_id != self.industry_id:
            raise ValueError("ALIAS_REFERENCE：产业ID与引用不一致")
        require_input_refs(self, (self.industry_ref,))
        return self


class CrosswalkSpec(Contract):
    crosswalk_id: Text
    external_system: Literal["SHENWAN", "CITIC", "GICS", "GB_T_4754", "EXCHANGE", "PROVIDER"]
    provider_name: Text | None = None
    external_code: Text
    external_name: Text
    x_industry_id: IndustryID | None = None
    mapping_type: Literal["EXACT", "BROADER", "NARROWER", "RELATED", "UNRESOLVED"]
    mapping_status: MappingStatus = "CANDIDATE"
    evidence_refs: Items[VersionRef] = ()
    provenance_zh: Chinese
    reviewed_by: Text | None = None

    @model_validator(mode="after")
    def gate(self):
        if (self.mapping_type == "UNRESOLVED") != (self.x_industry_id is None):
            raise ValueError("CROSSWALK_UNRESOLVED：未知映射不得猜测产业ID")
        if (self.mapping_type == "UNRESOLVED") != (self.mapping_status == "UNRESOLVED"):
            raise ValueError("CROSSWALK_STATUS：未解析映射必须标UNRESOLVED")
        if self.mapping_status == "VERIFIED" and (not self.evidence_refs or not self.reviewed_by):
            raise ValueError("MAPPING_PROOF：无证据/核验人不能VERIFIED")
        if self.external_system in ("PROVIDER", "EXCHANGE") and not self.provider_name:
            raise ValueError("EXTERNAL_SYSTEM：必须明确Provider或交易所名称")
        return self


class ExternalCrosswalk(DerivedEnvelope, CrosswalkSpec):
    ontology_version: Text
    industry_ref: VersionRef | None = None

    @model_validator(mode="after")
    def references(self):
        if (self.industry_ref.object_id if self.industry_ref else None) != self.x_industry_id:
            raise ValueError("CROSSWALK_REFERENCE：产业ID与引用不一致")
        require_input_refs(self, (self.industry_ref,) if self.industry_ref else ())
        return self


class ImpactRuleSpec(Contract):
    rule_id: Text
    variable_type: VariableType
    target_object: Target
    direction: Direction
    geography: Geography = "GLOBAL"
    fx_pair: CurrencyPair | None = None
    industry_id: IndustryID
    impact_direction: ImpactDirection
    path_role: PathRole
    mechanism_zh: Chinese
    evidence_refs: Items[VersionRef] = ()
    mapping_status: Literal["CANDIDATE", "VERIFIED", "HOLD"] = "CANDIDATE"
    reviewed_by: Text | None = None

    @model_validator(mode="after")
    def gate(self):
        if self.variable_type == "FX":
            if self.fx_pair is None or self.target_object != "CURRENCY" or self.direction == "UNKNOWN":
                raise ValueError("FX_RULE：FX映射规则也必须明确币种对与方向")
        elif self.fx_pair is not None or self.target_object == "CURRENCY":
            raise ValueError("FX_RULE：币种对只属于FX规则")
        if self.mapping_status == "VERIFIED" and (not self.evidence_refs or not self.reviewed_by):
            raise ValueError("MAPPING_PROOF：无证据/核验人不能VERIFIED")
        return self


class IndustryImpactRule(DerivedEnvelope, ImpactRuleSpec):
    ontology_version: Text
    industry_ref: VersionRef

    @model_validator(mode="after")
    def references(self):
        if self.industry_ref.object_id != self.industry_id:
            raise ValueError("RULE_REFERENCE：产业ID与引用不一致")
        require_input_refs(self, (self.industry_ref,))
        return self


class OntologyDraft(Contract):
    ontology_id: Literal["X_INDUSTRY"] = "X_INDUSTRY"
    version: PositiveInt
    segments: Items[SegmentSpec]
    aliases: Items[AliasSpec] = ()
    crosswalks: Items[CrosswalkSpec] = ()
    rules: Items[ImpactRuleSpec] = ()

    @model_validator(mode="after")
    def tree(self):
        nodes = {s.industry_id: s for s in self.segments}
        if not nodes or len(nodes) != len(self.segments):
            raise ValueError("INDUSTRY_DUPLICATE：产业树非空且ID不得重复")
        for s in self.segments:
            seen, node = set(), s
            while node.parent_id is not None:
                if node.industry_id in seen:
                    raise ValueError("INDUSTRY_CYCLE：产业树存在循环")
                seen.add(node.industry_id)
                if node.parent_id not in nodes:
                    raise ValueError("INDUSTRY_DANGLING：父产业不存在")
                node = nodes[node.parent_id]
            if (s.parent_id is None and s.level != 0) or (s.parent_id is not None and s.level != nodes[s.parent_id].level + 1):
                raise ValueError("INDUSTRY_LEVEL：层级与父节点不一致")
            if s.effective_to is not None and s.effective_to <= s.effective_from:
                raise ValueError("EFFECTIVE_INTERVAL：产业有效期错误")
        for items, name in ((self.aliases, "alias_id"), (self.crosswalks, "crosswalk_id"), (self.rules, "rule_id")):
            if len({getattr(r, name) for r in items}) != len(items):
                raise ValueError("ONTOLOGY_DUPLICATE：字典/规则ID重复")
        targets = [a.industry_id for a in self.aliases] + [c.x_industry_id for c in self.crosswalks if c.x_industry_id] + [r.industry_id for r in self.rules]
        if any(t not in nodes for t in targets):
            raise ValueError("INDUSTRY_DANGLING：alias/crosswalk/规则目标不存在")
        return self


class OntologyVersion(DerivedEnvelope):
    ontology_version: Text
    segment_refs: Items[VersionRef]
    alias_refs: Items[VersionRef]
    crosswalk_refs: Items[VersionRef]
    rule_refs: Items[VersionRef]

    @model_validator(mode="after")
    def references(self):
        require_input_refs(self, (*self.segment_refs, *self.alias_refs, *self.crosswalk_refs, *self.rule_refs))
        return self


class NarrativeTheme(DerivedEnvelope):
    event_ref: VersionRef
    theme_id: Text
    canonical_name_zh: Chinese
    description_zh: Chinese
    economic_path_status: Literal["UNRESOLVED"] = "UNRESOLVED"

    @model_validator(mode="after")
    def references(self):
        require_input_refs(self, (self.event_ref,))
        return self


class ThemeIndustryRelation(DerivedEnvelope):
    theme_ref: VersionRef
    ontology_ref: VersionRef
    industry_ref: VersionRef | None
    relation_status: Literal["ASSOCIATED", "UNRESOLVED"]
    mechanism_zh: Chinese

    @model_validator(mode="after")
    def references(self):
        if (self.industry_ref is None) != (self.relation_status == "UNRESOLVED") or not self.evidence_refs:
            raise ValueError("THEME_RELATION：关系状态/目标不一致或缺关联证据；不是经济暴露")
        require_input_refs(self, (self.theme_ref, self.ontology_ref, *([self.industry_ref] if self.industry_ref else [])))
        return self


class IndustryDirectionSummary(Contract):
    industry_ref: VersionRef | None
    impact_direction: ImpactDirection


class IndustryImpactCandidate(DerivedEnvelope):
    impact_ref: VersionRef
    industry_ref: VersionRef | None
    ontology_ref: VersionRef
    ontology_version: Text
    rule_ref: VersionRef | None
    impact_direction: ImpactDirection
    path_role: PathRole
    mapping_status: MappingStatus
    mechanism_zh: Chinese
    observation_kind: Literal["HYPOTHESIS"] = "HYPOTHESIS"
    uncertainty_zh: Chinese

    @model_validator(mode="after")
    def gate(self):
        if ((self.industry_ref is None) != (self.mapping_status == "UNRESOLVED")
                or (self.rule_ref is None) != (self.industry_ref is None)):
            raise ValueError("CANDIDATE_UNRESOLVED：未知产业不得伪造映射")
        if self.mapping_status == "VERIFIED":
            raise ValueError("CANDIDATE_HYPOTHESIS：产业影响候选不是已验证经济效果")
        require_input_refs(self, (self.impact_ref, self.ontology_ref, *([self.industry_ref] if self.industry_ref else []),
                                 *([self.rule_ref] if self.rule_ref else [])))
        return self


class IndustryResolution(DerivedEnvelope):
    impact_ref: VersionRef
    ontology_ref: VersionRef
    as_of: UTCDateTime
    candidate_refs: Items[VersionRef]
    industry_directions: Items[IndustryDirectionSummary] = ()

    @model_validator(mode="after")
    def references(self):
        require_input_refs(self, (self.impact_ref, self.ontology_ref, *self.candidate_refs))
        return self


class AliasResolution(Contract):
    phrase: Text
    as_of: UTCDateTime
    ontology_ref: VersionRef | None
    industry_ref: VersionRef | None
    alias_refs: Items[VersionRef] = ()
    mapping_status: Literal["MATCHED", "UNRESOLVED"]
    reason_zh: Chinese


SCHEMAS = {m.__name__: m for m in (ImpactVariable, IndustrySegment, IndustryAlias, ExternalCrosswalk,
    IndustryImpactRule, OntologyVersion, NarrativeTheme, ThemeIndustryRelation, IndustryImpactCandidate, IndustryResolution)}
