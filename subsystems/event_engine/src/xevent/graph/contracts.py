"""Phase 6 固定版本图契约；通用时间与校验复用 Pydantic。"""
from typing import Literal
from pydantic import Field, model_validator
from ..contracts.common import Contract, DerivedEnvelope, Items, Text, UTCDateTime, VersionRef, Band, Count
from ..contracts.models import require_input_refs, identity_matches
from ..ontology.contracts import Chinese, ImpactDirection
from ..exposures.contracts import ExposureType

POLICY = "X_TRANSMISSION_V0.1"
World = Literal["ECONOMIC", "NARRATIVE"]
MappingState = Literal["VERIFIED_DIRECT", "VERIFIED_INDIRECT", "PLAUSIBLE", "NARRATIVE_ONLY", "MIXED", "CONTRADICTED", "INVALID"]
NetState = Literal["POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN", "HOLD"]


class BuildRequest(Contract):
    event_ref: VersionRef
    resolution_refs: Items[VersionRef] = ()
    exposure_refs: Items[VersionRef] = ()
    snapshot_ref: VersionRef
    as_of: UTCDateTime

    @model_validator(mode="after")
    def unique(self):
        for values in (self.resolution_refs, self.exposure_refs):
            if len({(r.object_id,r.version) for r in values}) != len(values):
                raise ValueError("GRAPH_DUPLICATE_INPUT：固定输入不得重复")
        return self


class GraphEnvelope(DerivedEnvelope):
    as_of: UTCDateTime
    provenance_zh: Chinese

    @model_validator(mode="after")
    def cutoff(self):
        if self.as_of > self.computed_at:
            raise ValueError("GRAPH_PIT：知识截止不得晚于计算完成")
        return self


class EdgeVersion(GraphEnvelope):
    edge_id: Text
    from_ref: VersionRef
    to_ref: VersionRef
    edge_type: Literal["CAUSES", "BENEFITS", "HARMS", "HAS_EXPOSURE", "EXPOSURE_OF", "HAS_SECURITY",
        "EVOKES_THEME", "HAS_ASSOCIATION", "MARKET_ASSOCIATED_WITH"]
    world: World
    impact_direction: ImpactDirection
    strength_band: Band = "UNKNOWN"
    causal_confidence: Band = "UNKNOWN"
    mechanism_zh: Chinese
    inference_type: Literal["OBSERVED", "HYPOTHESIS", "STRUCTURAL", "NARRATIVE"]
    origin_cluster_ids: Items[Text] = ()

    @model_validator(mode="after")
    def edge_gate(self):
        identity_matches(self, "edge_id")
        require_input_refs(self, (self.from_ref, self.to_ref))
        if self.from_ref == self.to_ref:
            raise ValueError("GRAPH_CYCLE：边不能自指")
        if self.world == "NARRATIVE" and self.inference_type not in ("NARRATIVE", "STRUCTURAL"):
            raise ValueError("GRAPH_WORLD：叙事不得冒充经济事实")
        if any(r.available_at > self.as_of for r in self.input_version_refs):
            raise ValueError("GRAPH_PIT：边的原始输入必须截至as_of可知")
        return self


class TransmissionPath(GraphEnvelope):
    path_id: Text
    event_ref: VersionRef
    company_ref: VersionRef
    security_ref: VersionRef
    exposure_ref: VersionRef
    exposure_type: ExposureType
    world: World
    node_refs: Items[VersionRef] = Field(min_length=4)
    edge_refs: Items[VersionRef] = Field(min_length=3)
    graph_hop_count: Count
    economic_depth: Count
    impact_direction: ImpactDirection
    benefit_level: Literal["L1_DIRECT", "L2_FIRST_ORDER", "L3_SECOND_ORDER", "N1_NARRATIVE", "REJECT_WEAK_MAPPING"]
    mapping_state: MappingState
    research_status: Literal["CANDIDATE", "DEGRADED", "HOLD"]
    mechanism_zh: Chinese
    uncertainty_zh: Chinese
    origin_cluster_refs: Items[VersionRef] = ()
    origin_group_ids: Items[Text] = ()
    candidate_ref: VersionRef | None = None
    alternative_mechanism_refs: Items[VersionRef] = ()

    @model_validator(mode="after")
    def path_gate(self):
        identity_matches(self, "path_id")
        require_input_refs(self, (*self.node_refs, *self.edge_refs, self.exposure_ref,
            *self.origin_cluster_refs, *self.alternative_mechanism_refs, *([self.candidate_ref] if self.candidate_ref else [])))
        keys = [(r.object_id, r.version) for r in self.node_refs]
        if len(set(keys)) != len(keys) or len({r.object_id for r in self.node_refs}) != len(keys):
            raise ValueError("GRAPH_CYCLE：路径节点不能循环")
        if self.node_refs[0] != self.event_ref or self.node_refs[-2:] != (self.company_ref, self.security_ref):
            raise ValueError("GRAPH_ENDPOINT：事件/公司/证券端点错误")
        if self.graph_hop_count != len(self.edge_refs) or len(self.node_refs) != self.graph_hop_count + 1:
            raise ValueError("GRAPH_CONTINUITY：边数与节点不连续")
        if self.exposure_ref not in self.node_refs:
            raise ValueError("GRAPH_EXPOSURE：暴露必须是路径中的固定节点")
        originals=(*self.node_refs,*self.origin_cluster_refs,*self.alternative_mechanism_refs,
            *([self.candidate_ref] if self.candidate_ref else []))
        keys={(r.object_id,r.version) for r in originals}
        if any((r.object_id,r.version) in keys and r.available_at>self.as_of for r in self.input_version_refs):
            raise ValueError("GRAPH_PIT：路径原始节点不得晚于输入截止点；新生成边另按提交时间发布")
        if self.world == "NARRATIVE":
            if self.benefit_level != "N1_NARRATIVE" or self.mapping_state != "NARRATIVE_ONLY" or self.exposure_type != "NARRATIVE_ASSOCIATION" or self.economic_depth:
                raise ValueError("GRAPH_NARRATIVE：叙事只允许N1，不证明经济暴露")
        elif self.exposure_type == "NARRATIVE_ASSOCIATION" or self.benefit_level == "N1_NARRATIVE":
            raise ValueError("GRAPH_ECONOMIC：叙事不能进入经济链")
        if self.mapping_state == "VERIFIED_DIRECT" and self.exposure_type != "VERIFIED_DIRECT":
            raise ValueError("GRAPH_EXPOSURE：不得升级原始暴露")
        if self.economic_depth > 3 and self.research_status == "CANDIDATE":
            raise ValueError("GRAPH_DEPTH：超过三经济层必须软降级")
        return self


class MappingAssessment(GraphEnvelope):
    company_ref: VersionRef
    path_refs: Items[VersionRef]
    positive_path_refs: Items[VersionRef]
    negative_path_refs: Items[VersionRef]
    narrative_path_refs: Items[VersionRef]
    counter_path_refs: Items[VersionRef]
    net_effect_state: NetState
    strongest_counter_path_ref: VersionRef | None
    counter_selection_policy: Literal["DEPTH_THEN_FIXED_ID_NOT_ALPHA"] = "DEPTH_THEN_FIXED_ID_NOT_ALPHA"

    @model_validator(mode="after")
    def references(self):
        require_input_refs(self, (self.company_ref, *self.path_refs))
        if any(r not in self.path_refs for r in (*self.positive_path_refs, *self.negative_path_refs,
                *self.narrative_path_refs, *self.counter_path_refs)):
            raise ValueError("GRAPH_ASSESSMENT：分组必须属于原路径集合")
        if self.strongest_counter_path_ref and self.strongest_counter_path_ref not in self.counter_path_refs:
            raise ValueError("GRAPH_COUNTER：反路径引用缺失")
        return self


class MappingHistory(GraphEnvelope):
    request: BuildRequest
    path_refs: Items[VersionRef]
    assessment_refs: Items[VersionRef]
    previous_history_ref: VersionRef | None = None
    hold_reasons: Items[Text]

    @model_validator(mode="after")
    def references(self):
        require_input_refs(self, (*self.path_refs, *self.assessment_refs, self.request.event_ref,
            self.request.snapshot_ref, *self.request.resolution_refs, *self.request.exposure_refs,
            *([self.previous_history_ref] if self.previous_history_ref else [])))
        originals=(self.request.event_ref,self.request.snapshot_ref,*self.request.resolution_refs,*self.request.exposure_refs)
        keys={(r.object_id,r.version) for r in originals}
        if self.as_of != self.request.as_of or any((r.object_id,r.version) in keys and r.available_at>self.as_of for r in self.input_version_refs):
            raise ValueError("GRAPH_HISTORY_PIT：历史必须保持请求截止与原始输入门槛")
        return self


SCHEMAS = {c.__name__: c for c in (EdgeVersion, TransmissionPath, MappingAssessment, MappingHistory)}
