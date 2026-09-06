from datetime import timedelta
import json

import pytest

from test_phase3_states import world, receive, assess, evaluate, latest, vr
from test_phase2_ledger import setup_ledger, obs
from xevent.contracts import Source, NarrativeSourceProfile
from xevent.contracts.common import ObservationWindow
from xevent.ledger.contracts import EventSeed, RawObservation
from xevent.ledger.store import Ledger
from xevent.states.engine import StateEngine


@pytest.mark.pit
@pytest.mark.parametrize("operation",["MERGE","SPLIT"])
def test_lineage_asof_parent_ids_and_children(world,operation):
    ledger,clock,source,seed,engine,policy=world
    evidence=receive(world,"父事件证据")
    parents=[vr(latest(ledger,clock))]
    if operation=="MERGE":
        other=EventSeed(**{**seed.model_dump(),"event_id":"PARENT_B"})
        observation=obs(clock,source,"另一父事件",version="parent-b")
        ledger.ingest(RawObservation.model_validate({**observation.model_dump(),"locator":"fixture:parent-b"}),other)
        parents.append(vr(latest(ledger,clock,"PARENT_B")))
    children=[EventSeed(**{**seed.model_dump(),"event_id":f"CHILD_{n}"}) for n in range(1 if operation=="MERGE" else 2)]
    cutoff=clock()
    before=ledger.replay(cutoff)
    clock.advance(minutes=30)
    kwargs=dict(request_key=operation,interpretation_zh="人工核验事件身份，不单凭相似度",evidence_refs=[vr(evidence)],child_seeds=children)
    relation=engine.lineage(operation,parents,vr(policy),**kwargs)
    assert engine.lineage(operation,parents,vr(policy),**kwargs)==relation
    assert ledger.replay(cutoff)==before
    assert not ledger.history(as_of=cutoff,kind="EventLineage")
    now_ids={e.event_id for e in ledger.history(as_of=clock(),kind="EventVersion")}
    assert {r.object_id for r in parents} <= now_ids
    assert {r.object_id for r in relation.child_refs}=={s.event_id for s in children}
    assert len(engine.pending(as_of=clock()))==len(children)
    assert len({r.idempotency_key for r in engine.pending(as_of=clock())})==len(children)
    assert all(r.trigger_reasons==("LINEAGE_CHANGE",) for r in engine.pending(as_of=clock()))


@pytest.mark.pit
def test_archive_reactivate_new_material_preserves_old_world(world):
    ledger,clock,source,seed,engine,policy=world
    fields={"amount":"1"}
    evidence=receive(world,json.dumps(fields),structured_fields=fields,structured_basis="SOURCE_STRUCTURED",claim_kind="FACT",is_first_hand=True)
    a=assess(world,evidence,"OFFICIAL_CONFIRMATION",authority_scope_zh="负责机构")
    evaluate(world,"confirmed",assessment_refs=[vr(a)])
    relation=engine.lineage("ARCHIVE",[vr(latest(ledger,clock))],vr(policy),request_key="archive",interpretation_zh="停止主动研究")
    archived=latest(ledger,clock)
    assert archived.lifecycle_status=="ARCHIVED" and archived.fact_state=="OFFICIALLY_CONFIRMED"
    cutoff=clock()
    before=ledger.replay(cutoff)
    with pytest.raises(ValueError,match="LINEAGE_MATERIAL"):
        engine.lineage("REACTIVATE",[vr(archived)],vr(policy),request_key="bad",interpretation_zh="旧材料",evidence_refs=[vr(evidence)])
    clock.advance(minutes=10)
    fields["amount"]="2"
    new=receive(world,json.dumps(fields),version="2",change_type="EDIT",structured_fields=fields,structured_basis="SOURCE_STRUCTURED",claim_kind="FACT",is_first_hand=True)
    assert latest(ledger,clock).lifecycle_status=="ARCHIVED"
    novelty=ledger.history(as_of=clock(),kind="NoveltyDecision")[-1]
    engine.lineage("REACTIVATE",[vr(latest(ledger,clock))],vr(policy),request_key="reactivate",interpretation_zh="新material恢复主动研究",evidence_refs=[vr(new)],novelty_ref=vr(novelty))
    assert latest(ledger,clock).lifecycle_status=="ACTIVE"
    assert ledger.replay(cutoff)==before
    assert ledger.get(archived.object_id,archived.version).lifecycle_status=="ARCHIVED"


@pytest.mark.pit
def test_mutate_requires_r4_and_keeps_version(world):
    ledger,clock,source,seed,engine,policy=world
    fields={"legal_status":"draft"}
    receive(world,json.dumps(fields),structured_fields=fields,structured_basis="SOURCE_STRUCTURED")
    cutoff=clock()
    before=ledger.replay(cutoff)
    fields["legal_status"]="law"
    evidence=receive(world,json.dumps(fields),version="2",change_type="EDIT",structured_fields=fields,structured_basis="SOURCE_STRUCTURED")
    novelty=ledger.history(as_of=clock(),kind="NoveltyDecision")[-1]
    changed=EventSeed(**{**seed.model_dump(),"dna":{**seed.dna.model_dump(),"action_code":"LAW_ENACTED"}})
    relation=engine.lineage("MUTATE",[vr(latest(ledger,clock))],vr(policy),request_key="mutate",interpretation_zh="意图成为法律",evidence_refs=[vr(evidence)],novelty_ref=vr(novelty),mutated_seed=changed)
    assert relation.operation=="MUTATE" and relation.child_refs[0].version==3
    assert latest(ledger,clock).dna.action_code=="LAW_ENACTED"
    assert ledger.replay(cutoff)==before


def test_lineage_crash_rolls_back_all_children(world):
    ledger,clock,source,seed,engine,policy=world
    evidence=receive(world)
    before=ledger.replay(clock())
    children=[EventSeed(**{**seed.model_dump(),"event_id":f"CHILD_{n}"}) for n in range(2)]
    def fault(stage):
        if stage=="after_lineage":
            raise RuntimeError("模拟Lineage崩溃")
    ledger.fault=fault
    with pytest.raises(RuntimeError):
        engine.lineage("SPLIT",[vr(latest(ledger,clock))],vr(policy),request_key="crash",interpretation_zh="拆分",evidence_refs=[vr(evidence)],child_seeds=children)
    assert ledger.replay(clock())==before


def test_cooldown_coalesces_diffusion_but_denial_is_immediate(world):
    ledger,clock,source,seed,engine,policy=world
    original=receive(world,claim_kind="RUMOR")
    for n in range(5):
        media=ledger.register_source(Source.model_validate({**source.model_dump(),"source_id":f"MEDIA{n}","object_id":f"MEDIA{n}","tier":"S1"}))
        ledger.ingest(obs(clock,media,f"传播{n}",origin_ref=vr(original),claim_kind="RUMOR"),seed)
        if n==2:
            assert evaluate(world,"rapid").narrative_state=="RAPID_DIFFUSION"
    assert evaluate(world,"mainstream").narrative_state=="MAINSTREAM"
    ordinary=ledger.history(as_of=clock(),kind="RecomputeTrigger")
    assert [r.dispatch for r in ordinary]==["READY","COALESCED"]
    denial=receive(world,"官方否认",locator="fixture:denial",claim_kind="FACT",is_first_hand=True)
    a=assess(world,denial,"OFFICIAL_DENIAL",authority_scope_zh="负责机构")
    state=evaluate(world,"denial",assessment_refs=[vr(a)])
    assert state.priority=="P0"
    trigger=engine.pending(as_of=clock())[0]
    assert trigger.priority=="P0" and trigger.dispatch=="READY" and trigger.cooldown_parent_ref is None
    clock.advance(minutes=10)
    pending=engine.pending(as_of=clock())
    assert len(pending)==2
    assert any(r.dispatch=="COALESCED" and r.event_ref==ordinary[-1].event_ref for r in pending)


def test_r5_bypasses_cooldown(world):
    ledger,clock,source,seed,engine,policy=world
    fields={"retracted":"false"}
    original=receive(world,json.dumps(fields),structured_fields=fields,structured_basis="SOURCE_STRUCTURED",is_first_hand=True)
    evaluate(world,"primary-before-diffusion")
    for n in range(3):
        media=ledger.register_source(Source.model_validate({**source.model_dump(),"source_id":f"M{n}","object_id":f"M{n}"}))
        ledger.ingest(obs(clock,media,f"转发{n}",origin_ref=vr(original)),seed)
    evaluate(world,"diffusion")
    assert any(r.trigger_reasons==("NARRATIVE_ACCELERATION",) for r in engine.pending(as_of=clock()))
    fields["retracted"]="true"
    receive(world,json.dumps(fields),version="2",change_type="EDIT",structured_fields=fields,structured_basis="SOURCE_STRUCTURED",is_first_hand=True)
    state=evaluate(world,"r5")
    assert state.fact_state=="UNVERIFIED"
    assert engine.pending(as_of=clock())[0].priority=="P0"


@pytest.mark.pit
def test_profile_sample_and_followers_do_not_confirm_fact(world,payload):
    ledger,clock,source,seed,engine,policy=world
    receive(world,claim_kind="RUMOR")
    data=payload["narrative_source_profiles"][0]
    # 画像引用的Phase1证据不在此Ledger，明确使用本次已保存来源版本与证据。
    evidence=ledger.history(as_of=clock(),kind="EvidenceVersion")[0]
    now=clock()
    common=dict(recorded_at=now,available_at=now,computed_at=now,
        input_version_refs=[{**vr(source).model_dump(),"available_at":source.available_at},
                            {**vr(evidence).model_dump(),"available_at":evidence.available_at}],
        evidence_refs=[vr(evidence).model_dump()],source_ref=vr(source).model_dump(),source_id=source.source_id,
        topic_id=seed.dna.domain_ids[0],category="EXPLAINER",followers=99999999,sample_n=0,
        observation_window={"start":now-timedelta(minutes=5),"end":now},leading_stats=None,
        following_stats=None,posthoc_stats=None,edit_stats=None,delete_stats=None,lead_time_stats=None)
    p=engine.register_profile(NarrativeSourceProfile.model_validate({**data,**common}))
    state=evaluate(world,"no-sample",profile_refs=[vr(p)])
    assert state.fact_state=="UNVERIFIED" and state.narrative_state=="QUIET"
    cutoff=clock()
    before=ledger.replay(cutoff)
    now=clock()
    new=engine.register_profile(NarrativeSourceProfile.model_validate({**p.model_dump(),"version":2,"sample_n":5,"recorded_at":now,"computed_at":now,"available_at":now}))
    state=evaluate(world,"profile-sample",profile_refs=[vr(new)])
    assert state.narrative_state=="PROFESSIONAL_DISCOVERY" and state.fact_state=="UNVERIFIED"
    assert ledger.replay(cutoff)==before


@pytest.mark.pit
def test_restart_replay_and_json_roundtrip(world):
    ledger,clock,source,seed,engine,policy=world
    receive(world)
    evaluate(world,"before-restart")
    cutoff=clock()
    before=ledger.replay(cutoff)
    for record in ledger.history(as_of=cutoff):
        assert type(record).model_validate_json(record.model_dump_json())==record
    ledger.close()
    recovered=Ledger(ledger.path,clock=clock)
    assert recovered.replay(cutoff)==before==recovered.replay(cutoff)
    recovered.close()
