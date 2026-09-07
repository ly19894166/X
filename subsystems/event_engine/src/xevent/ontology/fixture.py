"""新的隔离演示库；仅离线虚构输入，复用Source/Evidence/Event摄取。"""
import json
from datetime import timedelta

from ..contracts import Source
from ..contracts.common import TypeAdapter, UTCDateTime, VersionRef
from ..ledger.contracts import EventSeed, RawObservation
from ..ledger.store import Ledger, ref
from .contracts import ImpactSpec, OntologyDraft
from .engine import OntologyEngine


def run_fixture(path, db):
    if db.exists():
        raise ValueError("FIXTURE_DB：只允许新的隔离演示库")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    base = json.loads((path.parent / data["base_fixture"]).read_text(encoding="utf-8-sig"))
    class Clock:
        value = TypeAdapter(UTCDateTime).validate_python(data["at"])
        def __call__(self):
            self.value += timedelta(milliseconds=1)
            return self.value
    clock = Clock()
    ledger = Ledger(db, clock=clock)
    def vr(obj):
        return VersionRef(**ref(obj))
    try:
        source = ledger.register_source(Source.model_validate(base["sources"][0]))
        seed = EventSeed(event_id="PHASE4_FIXTURE", title_zh="虚构铜减产公告",
                         dna={**base["event_versions"][0]["dna"], "actor_refs": []})
        raw = "虚构负责机构宣布铜供应减少；尚未观察到铜价上涨"
        evidence = ledger.ingest(RawObservation(source_ref=ref(source), locator="fixture:phase4",
            raw=raw.encode(), first_seen_at=clock(), collected_at=clock(), content_version="1",
            claim_kind="FACT", is_first_hand=True), seed)
        event = ledger.history(as_of=clock(), kind="EventVersion")[-1]
        engine = OntologyEngine(ledger)
        ontology = engine.publish(OntologyDraft.model_validate(data["ontology"]))
        observed = engine.impact("IMPACT_SUPPLY", 1, ImpactSpec(event_ref=vr(event), variable_type="SUPPLY",
            target_object="COPPER", direction="DOWN", geography="GLOBAL", observation_kind="OBSERVED",
            evidence_refs=[ref(evidence)], mechanism_zh="公告明确宣布供应减少，记录宣布事实而非已实现产量",
            observation_basis=dict(evidence_ref=ref(evidence), quoted_span=raw, reviewed_by="虚构fixture核验者",
                interpretation_zh="仅标注已宣布供应变化", scope="ANNOUNCED_CHANGE")))
        hypothesis = engine.impact("IMPACT_PRICE", 1, ImpactSpec(event_ref=vr(event), variable_type="PRICE",
            target_object="COPPER", direction="UP", geography="GLOBAL", observation_kind="HYPOTHESIS",
            premise_refs=[ref(observed)], evidence_refs=[ref(evidence)], mechanism_zh="供应减少可能提高铜价",
            uncertainty_zh="库存、需求和替代供应可能抵消减产", validation_status="UNREVIEWED"))
        resolution = engine.resolve(vr(hypothesis), vr(ontology), as_of=clock(), request_key="fixture")
        candidates = [ledger.get(r.object_id, r.version) for r in resolution.candidate_refs]
        theme = engine.theme("THEME_COMPUTE_POWER", 1, event_ref=vr(event), canonical_name_zh="算力电力",
            description_zh="独立叙事fixture；不猜产业归属", evidence_refs=[vr(evidence)])
        old_cutoff = clock.value.replace(minute=30, second=0, microsecond=0)
        old = engine.resolve_alias("上游铜资源", as_of=old_cutoff)
        clock.value = clock.value.replace(hour=clock.value.hour+1, minute=0, second=0, microsecond=0)
        newer = {**data["ontology"], "version": 2, "aliases": [dict(alias_id="upstream-copper", phrase="上游铜资源", industry_id="XIND_COPPER_MINING")]}
        engine.publish(OntologyDraft.model_validate(newer))
        later = engine.resolve_alias("上游铜资源", as_of=clock.value.replace(minute=30))
        if engine.resolve_alias("上游铜资源", as_of=old_cutoff) != old:
            raise ValueError("PIT_ALIAS：晚到alias污染旧时点")
        if ledger.history(as_of=clock(), kind="EventVersion") != [event]:
            raise ValueError("EVENT_WRITE：Phase4不应修改事件")
        return {"声明": data["description_zh"], "观察": {"类型":observed.variable_type, "方向":observed.direction, "性质":observed.observation_kind},
            "推断": {"类型":hypothesis.variable_type, "方向":hypothesis.direction, "性质":hypothesis.observation_kind},
            "产业候选": [{"产业":c.industry_ref.object_id, "影响":c.impact_direction, "状态":c.mapping_status, "机制":c.mechanism_zh} for c in candidates],
            "主题": {"名称":theme.canonical_name_zh, "经济路径":theme.economic_path_status},
            "晚到别名": {"10:30回放":old.mapping_status, "11:30解析":later.mapping_status}, "事件状态": "未修改"}
    finally:
        ledger.close()
