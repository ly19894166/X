"""冻结字段的无损导出投影；不写Ledger，不建立第二份关系数据源。"""
from typing import Literal

from pydantic import model_validator

from ..contracts.common import Contract, Items, UTCDateTime, VersionRef
from .contracts import (ExternalCrosswalk, IndustrySegment, NarrativeTheme, OntologyVersion,
                        ThemeIndustryRelation)


def keys(items):
    return {(r.object_id, r.version) for r in items}


def references(items):
    return tuple(VersionRef(object_id=k[0], version=k[1]) for k in sorted(keys(items)))


class FrozenNarrativeTheme(NarrativeTheme):
    related_industry_refs: Items[VersionRef]
    association_evidence_refs: Items[VersionRef]
    relation_refs: Items[VersionRef]


class FrozenIndustrySegment(IndustrySegment):
    external_crosswalks: Items[VersionRef]


class FrozenOntologyView(Contract):
    compatibility_version: Literal["X_EVENT_V0.1_A1"] = "X_EVENT_V0.1_A1"
    as_of: UTCDateTime
    ontology: OntologyVersion
    theme: FrozenNarrativeTheme
    segments: Items[FrozenIndustrySegment]
    crosswalks: Items[ExternalCrosswalk]
    relations: Items[ThemeIndustryRelation]

    @model_validator(mode="after")
    def projection_consistency(self):
        all_records = (self.ontology, self.theme, *self.segments, *self.crosswalks, *self.relations)
        if any(r.available_at > self.as_of or r.mode != "LIVE_FORWARD" for r in all_records):
            raise ValueError("PIT_FROZEN_VIEW：未来或模拟记录不得进入实盘兼容视图")
        if (keys(self.segments) != keys(self.ontology.segment_refs)
                or keys(self.crosswalks) != keys(self.ontology.crosswalk_refs)):
            raise ValueError("FROZEN_MANIFEST：必须保持固定本体成员完整")
        if len({r.object_id for r in self.relations}) != len(self.relations):
            raise ValueError("FROZEN_RELATION：每个关系ID只能包含截止时点的一个版本")
        if any(c.industry_ref and not keys([c.industry_ref]) <= keys(self.segments) for c in self.crosswalks):
            raise ValueError("FROZEN_SCOPE：crosswalk目标不属于固定本体")
        for relation in self.relations:
            if keys([relation.theme_ref]) != keys([self.theme]) or keys([relation.ontology_ref]) != keys([self.ontology]):
                raise ValueError("FROZEN_SCOPE：主题关系来自错误主题/本体版本")
            if relation.industry_ref and not keys([relation.industry_ref]) <= keys(self.segments):
                raise ValueError("FROZEN_SCOPE：关系目标不在固定本体中")
        related = references(r.industry_ref for r in self.relations if r.industry_ref)
        evidence = references([*self.theme.evidence_refs, *(e for r in self.relations for e in r.evidence_refs)])
        if (self.theme.related_industry_refs != related or self.theme.association_evidence_refs != evidence
                or self.theme.relation_refs != references(self.relations)):
            raise ValueError("FROZEN_PROJECTION：主题关联投影与唯一正规化来源不一致")
        for segment in self.segments:
            expected = references(c for c in self.crosswalks if c.industry_ref and keys([c.industry_ref]) == keys([segment]))
            if segment.external_crosswalks != expected:
                raise ValueError("FROZEN_PROJECTION：产业crosswalk投影不一致")
        return self

    def normalized(self):
        """导出JSON往返后恢复原对象，保留原始版本/证据/时间；不写回历史库。"""
        return dict(ontology=self.ontology,
            theme=NarrativeTheme.model_validate(self.theme.model_dump(exclude={"related_industry_refs", "association_evidence_refs", "relation_refs"})),
            segments=tuple(IndustrySegment.model_validate(s.model_dump(exclude={"external_crosswalks"})) for s in self.segments),
            crosswalks=self.crosswalks, relations=self.relations)


def export_frozen_view(engine, theme_ref, ontology_ref, *, as_of):
    from ..contracts.common import TypeAdapter
    from .engine import key
    cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
    view = {key(r):r for r in engine.ledger.history(as_of=cutoff)}
    theme = engine._input(view, theme_ref, NarrativeTheme, cutoff)
    ontology = engine._input(view, ontology_ref, OntologyVersion, cutoff)
    crosswalks = tuple(view[key(r)] for r in ontology.crosswalk_refs)
    latest = {}
    for r in view.values():
        if isinstance(r, ThemeIndustryRelation) and r.theme_ref == theme_ref and r.ontology_ref == ontology_ref:
            if r.object_id not in latest or latest[r.object_id].version < r.version:
                latest[r.object_id] = r
    relations = tuple(latest[k] for k in sorted(latest))
    frozen_theme = FrozenNarrativeTheme.model_validate({**theme.model_dump(),
        "related_industry_refs":references(r.industry_ref for r in relations if r.industry_ref),
        "association_evidence_refs":references([*theme.evidence_refs, *(e for r in relations for e in r.evidence_refs)]),
        "relation_refs":references(relations)})
    segments = []
    for r in ontology.segment_refs:
        segment = view[key(r)]
        segments.append(FrozenIndustrySegment.model_validate({**segment.model_dump(),
            "external_crosswalks":references(c for c in crosswalks if c.industry_ref == r)}))
    return FrozenOntologyView(as_of=cutoff, ontology=ontology, theme=frozen_theme,
                              segments=segments, crosswalks=crosswalks, relations=relations)
