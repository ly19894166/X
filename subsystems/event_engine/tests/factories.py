"""确定性虚构数据；这里只声明提交时间，绝不模拟数据库已验收。"""
import hashlib

from xevent.contracts import (
    Actor, ActorTopicProfile, EvidenceRelation, EvidenceVersion, EventDNA,
    EventVersion, NarrativeSourceProfile, Source, SourceTopicProfile, Statement,
)
from xevent.contracts.bundle import content_digest
from xevent.contracts.common import InputVersionRef, VersionRef


def ts(second=0):
    return f"2026-09-06T10:00:{second:02d}+08:00"


def ref(record):
    return VersionRef(object_id=record.object_id, version=record.version)


def envelope(identity, second=0, inputs=()):
    return dict(object_id=identity, version=1, recorded_at=ts(second), available_at=ts(second),
                run_id="FIXTURE_离线_001", policy_version="PHASE1_V0.1", content_hash="0" * 64,
                input_version_refs=[InputVersionRef(**ref(r).model_dump(), available_at=r.available_at) for r in inputs])


def seal(record):
    return type(record).model_validate({**record.model_dump(), "content_hash": content_digest(record)})


def build_fixture():
    source = seal(Source(**envelope("SRC_虚构机构"), source_id="SRC_虚构机构", name_zh="离线虚构政策机构",
                         platform="OFFLINE", canonical_locator="fixture:source", tier="S0", roles=["FACT", "NARRATIVE"],
                         access_method="仅本地fixture", retention_policy="仅虚构测试内容"))
    actor = seal(Actor(**envelope("ACT_虚构发言人", inputs=(source,)), actor_id="ACT_虚构发言人", name_zh="虚构发言人",
                       entity_type="PERSON", verified_accounts=[ref(source)]))
    raw = "【虚构离线样例】机构拟研究新增算力供电试点；尚未实施，不能视为已确认订单。"
    evidence = seal(EvidenceVersion(**envelope("EVD_001", 5, (source,)), evidence_id="EVD_001", source_id=source.source_id,
                    source_ref=ref(source), canonical_url_or_locator="fixture:声明", original_language="zh-CN",
                    raw_object_ref="RAW_001", raw_content_hash=hashlib.sha256(raw.encode()).hexdigest(),
                    first_seen_text_ref="RAW_001", origin_cluster_id="ORIGIN_待Phase2识别_001", is_first_hand=True,
                    independence_status="UNKNOWN", claim_kind="INTENT", published_at=ts(), public_available_at=ts(),
                    first_seen_at=ts(1), collected_at=ts(2), ready_at=ts(5), evidence_type="OFFICIAL_DOCUMENT", quality_status="VALIDATED"))
    statement = seal(Statement(**envelope("STMT_001", 6, (source, actor, evidence)), computed_at=ts(6),
                              actor_id=actor.actor_id, actor_ref=ref(actor), source_id=source.source_id, source_ref=ref(source),
                              topic_id="DATACENTER_POWER", statement_type="PRESS_CONFERENCE", claim_kind="INTENT", evidence_ref=ref(evidence)))
    dna = EventDNA(actor_refs=[ref(actor)], action_code="PROPOSE_PILOT", object_entities=[
        dict(entity_id="OBJ_POWER_PILOT", entity_type="OBJECT", name_zh="算力供电试点")], domain_ids=["DATACENTER_POWER"],
        geographic_scope=["CN"], temporal_scope="试点时间未定", identity_rule_version="DNA_V0.1")
    event = seal(EventVersion(**envelope("EV_001", 8, (actor, evidence, statement)), computed_at=ts(7), event_id="EV_001",
                             title_zh="虚构供电试点研究意向", event_type="POLICY", dna=dna, evidence_refs=[ref(evidence)],
                             first_public_at=ts(), first_seen_at=ts(1), last_material_update_at=ts(6), revision_reason="首次离线契约样例"))
    source_profile = seal(SourceTopicProfile(**envelope("SP_001", 9, (source, evidence)), computed_at=ts(9), source_id=source.source_id,
                                           source_ref=ref(source), topic_id="DATACENTER_POWER", evidence_refs=[ref(evidence)]))
    narrative = seal(NarrativeSourceProfile(**envelope("NSP_001", 9, (source, evidence)), computed_at=ts(9), source_id=source.source_id,
                           source_ref=ref(source), topic_id="DATACENTER_POWER", evidence_refs=[ref(evidence)], category="UNKNOWN", sample_n=1,
                           observation_window=dict(start=ts(), end=ts(5)), missing_reason="小样本，传播与兑现统计尚未知"))
    actor_profile = seal(ActorTopicProfile(**envelope("AP_001", 9, (actor, statement)), computed_at=ts(9), actor_id=actor.actor_id,
                         actor_ref=ref(actor), topic_id="DATACENTER_POWER", statement_count=1, realized_count=0, partial_count=0,
                         denied_count=0, unresolved_count=1))
    relation = seal(EvidenceRelation(**envelope("REL_001", 9, (event, evidence)), computed_at=ts(9), subject_ref=ref(event), evidence_ref=ref(evidence),
                                    relation="CONTEXT", quoted_span=raw, interpretation_zh="仅证明发言内容，不证明试点实施或公司订单"))
    groups = dict(sources=[source], actors=[actor], evidence_versions=[evidence], statements=[statement], event_versions=[event],
                  source_topic_profiles=[source_profile], narrative_source_profiles=[narrative], actor_topic_profiles=[actor_profile],
                  evidence_relations=[relation])
    return {**{k: [r.model_dump(mode="json") for r in records] for k, records in groups.items()}, "raw_contents": {"RAW_001": raw}}
