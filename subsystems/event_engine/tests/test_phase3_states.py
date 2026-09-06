from datetime import timedelta
import json

import pytest
from pydantic import ValidationError

from test_phase2_ledger import setup_ledger, obs
from xevent.contracts import Source, NarrativeSourceProfile
from xevent.contracts.common import ObservationWindow, VersionRef
from xevent.ledger.contracts import EventSeed, RawObservation
from xevent.ledger.store import Ledger, ref
from xevent.states.engine import StateEngine
from xevent.states.contracts import Rules, SCHEMAS
from xevent.states.reducers import check_transition, ALLOWED, FORBIDDEN


def vr(obj):
    return VersionRef(**ref(obj))


def latest(ledger, clock, event_id="EVENT_P2"):
    return max((e for e in ledger.history(as_of=clock(), kind="EventVersion") if e.event_id==event_id), key=lambda e:e.version)


@pytest.fixture
def world(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    engine = StateEngine(ledger)
    policy = engine.policy()
    return ledger, clock, source, seed, engine, policy


def receive(world, text="虚构消息", *, locator="fixture:policy", **kwargs):
    ledger, clock, source, seed, engine, policy = world
    observation = obs(clock, source, text, **kwargs)
    observation = RawObservation.model_validate({**observation.model_dump(), "locator":locator})
    return ledger.ingest(observation, seed)


def assess(world, evidence, kind, key=None, **kwargs):
    ledger, clock, source, seed, engine, policy = world
    return engine.assess(vr(latest(ledger,clock,seed.event_id)),vr(evidence), assessment_key=key or kind,
        kind=kind,quoted_span=ledger.raw(evidence.raw_object_ref).decode(),reviewed_by="离线fixture核验者",
        interpretation_zh="虚构事件对应主张已人工标注", **kwargs)


def evaluate(world, key, **kwargs):
    ledger, clock, source, seed, engine, policy = world
    return engine.evaluate(vr(latest(ledger,clock,seed.event_id)),vr(policy),request_key=key,as_of=clock(),**kwargs)


def test_rumor_rapid_diffusion_does_not_confirm_fact(world):
    ledger, clock, source, seed, engine, policy = world
    original = receive(world, claim_kind="RUMOR")
    first = evaluate(world,"quiet")
    assert first.fact_state=="UNVERIFIED" and first.narrative_state=="QUIET"
    for n in range(3):
        media = ledger.register_source(Source.model_validate({**source.model_dump(),"source_id":f"MEDIA{n}","object_id":f"MEDIA{n}"}))
        ledger.ingest(obs(clock,media,f"虚构转述{n}",origin_ref=vr(original),claim_kind="RUMOR"),seed)
    state = evaluate(world,"rapid")
    assert state.fact_state=="UNVERIFIED" and state.narrative_state=="RAPID_DIFFUSION"
    assert state.pricing_state=="UNKNOWN"


def test_official_confirmation_then_new_implementation(world):
    ledger,clock,source,seed,engine,policy=world
    evidence=receive(world,"正式宣布",claim_kind="FACT",is_first_hand=True)
    confirmation=assess(world,evidence,"OFFICIAL_CONFIRMATION",authority_scope_zh="虚构负责机构")
    state=evaluate(world,"confirm",assessment_refs=[vr(confirmation)])
    assert state.fact_state=="OFFICIALLY_CONFIRMED"
    assert evaluate(world,"time-alone").fact_state=="OFFICIALLY_CONFIRMED"
    with pytest.raises(ValueError,match="IMPLEMENTATION_NEW"):
        assess(world,evidence,"IMPLEMENTATION")
    clock.advance(minutes=10)
    executed=receive(world,"新增执行文件",locator="fixture:execution",claim_kind="FACT",is_first_hand=True)
    implementation=assess(world,executed,"IMPLEMENTATION")
    assert evaluate(world,"execute",assessment_refs=[vr(implementation)]).fact_state=="IMPLEMENTED"


@pytest.mark.parametrize("same_source",[True,False])
def test_fact_confirmation_uses_supporting_independent_sources(world,same_source):
    ledger,clock,source,seed,engine,policy=world
    a=receive(world,"一手材料一",claim_kind="FACT",is_first_hand=True)
    aa=assess(world,a,"SUPPORT","a")
    other=source if same_source else ledger.register_source(Source.model_validate({**source.model_dump(),"source_id":"SECOND","object_id":"SECOND"}))
    bobs=obs(clock,other,"一手材料二",claim_kind="FACT",is_first_hand=True)
    b=ledger.ingest(RawObservation.model_validate({**bobs.model_dump(),"locator":"fixture:second"}),seed)
    bb=assess(world,b,"SUPPORT","b")
    state=evaluate(world,"independent",assessment_refs=[vr(aa),vr(bb)])
    assert state.fact_state==("PLAUSIBLE" if same_source else "INDEPENDENTLY_CONFIRMED")


def test_unassessed_independent_rumor_not_support(world):
    ledger,clock,source,seed,engine,policy=world
    a=receive(world,"一手事实",claim_kind="FACT",is_first_hand=True)
    aa=assess(world,a,"SUPPORT")
    other=ledger.register_source(Source.model_validate({**source.model_dump(),"source_id":"SECOND","object_id":"SECOND"}))
    ledger.ingest(obs(clock,other,"独立一手但仅传闻",claim_kind="RUMOR",is_first_hand=True),seed)
    assert evaluate(world,"support-only",assessment_refs=[vr(aa)]).fact_state=="PLAUSIBLE"


@pytest.mark.parametrize("kind,expected",[("OFFICIAL_DENIAL","CONTRADICTED"),("INVALIDATION","INVALIDATED"),("COUNTEREVIDENCE","CONTRADICTED")])
def test_negative_evidence_p0_not_bullish(world,kind,expected):
    evidence=receive(world,"虚构反证",claim_kind="FACT",is_first_hand=True)
    a=assess(world,evidence,kind,authority_scope_zh="负责机构" if kind=="OFFICIAL_DENIAL" else None)
    state=evaluate(world,"negative",assessment_refs=[vr(a)])
    assert state.fact_state==expected and state.priority=="P0"
    assert world[4].pending(as_of=world[1]())[-1].dispatch=="READY"
    world[1].advance(days=10)
    assert evaluate(world,"ten-days").fact_state==expected


@pytest.mark.parametrize("price",["UNKNOWN","NO_REACTION","INITIAL_REACTION","LOCAL_REPRICING","SECTOR_DIFFUSION","FULLY_PRICED","OVERTRADED"])
def test_price_dimension_fixture_never_confirms_fact(world,price):
    ledger,clock,source,seed,engine,policy=world
    evidence=receive(world,"虚构价格观察",claim_kind="NARRATIVE")
    observation=engine.price(vr(latest(ledger,clock)),observation_key=price,security_id="000001",
        window=ObservationWindow(start=clock.value-timedelta(minutes=1),end=clock()),observation=price,
        evidence_refs=[vr(evidence)],basis_zh="离线价格分段，非真实行情")
    state=evaluate(world,price,price_refs=[vr(observation)])
    assert state.fact_state=="UNVERIFIED" and state.pricing_state==price
    assert observation.security_id=="000001"


def test_official_and_no_reaction_can_coexist(world):
    ledger,clock,source,seed,engine,policy=world
    evidence=receive(world,"官方确认且价格无反应fixture",claim_kind="FACT",is_first_hand=True)
    a=assess(world,evidence,"OFFICIAL_CONFIRMATION",authority_scope_zh="负责机构")
    p=engine.price(vr(latest(ledger,clock)),observation_key="none",security_id="FIXTURE",
        window=ObservationWindow(start=clock.value-timedelta(minutes=1),end=clock()),observation="NO_REACTION",evidence_refs=[vr(evidence)],basis_zh="虚构")
    state=evaluate(world,"mixed-worlds",assessment_refs=[vr(a)],price_refs=[vr(p)])
    assert (state.fact_state,state.pricing_state)==("OFFICIALLY_CONFIRMED","NO_REACTION")


@pytest.mark.pit
def test_rumor_confirmation_denial_timeline_and_replay(world):
    ledger,clock,source,seed,engine,policy=world
    clock.value=clock.value.replace(hour=10,minute=0,second=0,microsecond=0)
    receive(world,"10点传闻",claim_kind="RUMOR")
    evaluate(world,"10")
    cutoff=clock.value.replace(minute=15)
    before=ledger.replay(cutoff)
    for minute,text,kind in ((30,"10点30确认","OFFICIAL_CONFIRMATION"),(60,"11点否认","OFFICIAL_DENIAL")):
        clock.value=clock.value.replace(hour=10+minute//60,minute=minute%60,second=0,microsecond=0)
        evidence=receive(world,text,locator=f"fixture:{minute}",claim_kind="FACT",is_first_hand=True)
        a=assess(world,evidence,kind,authority_scope_zh="负责机构")
        evaluate(world,text,assessment_refs=[vr(a)])
    assert ledger.replay(cutoff)==before==ledger.replay(cutoff)
    assert {r.new_state for r in ledger.history(as_of=cutoff,kind="StateTransition") if r.dimension=="FACT"}=={"UNVERIFIED"}
    assert latest(ledger,clock).fact_state=="CONTRADICTED"


@pytest.mark.pit
@pytest.mark.parametrize("level",["R1","R2","UNDETERMINED","R3","R4","R5"])
def test_material_clock_inherited_from_phase2(world,level):
    ledger,clock,source,seed,engine,policy=world
    fields={"amount":"1","detail":"a","legal_status":"draft","retracted":"false"}
    evidence=receive(world,json.dumps(fields),structured_fields=fields,structured_basis="SOURCE_STRUCTURED",is_first_hand=True)
    initial=evaluate(world,"initial")
    old_clock=ledger.get(*key_of_ref(initial.clock_ref))
    cutoff=clock()
    before=ledger.replay(cutoff)
    clock.advance(minutes=15)
    if level=="R1":
        new=receive(world,"转载",locator="fixture:repost",origin_ref=vr(evidence))
    elif level=="UNDETERMINED":
        new=receive(world,"普通编辑",version="2",change_type="EDIT")
    else:
        field,value={"R2":("detail","b"),"R3":("amount","2"),"R4":("legal_status","law"),"R5":("retracted","true")}[level]
        fields[field]=value
        new=receive(world,json.dumps(fields),version="2",change_type="EDIT",structured_fields=fields,structured_basis="SOURCE_STRUCTURED",is_first_hand=True)
    state=evaluate(world,"updated")
    clock_record=ledger.get(*key_of_ref(state.clock_ref))
    if level in ("R3","R4","R5"):
        assert clock_record.last_material_update_at==new.ready_at>old_clock.last_material_update_at
    else:
        assert clock_record.last_material_update_at==old_clock.last_material_update_at
    assert clock_record.observed_age_seconds>old_clock.observed_age_seconds
    assert ledger.replay(cutoff)==before
    if level=="R5":
        assert state.fact_state=="CONTRADICTED" and state.priority=="P0"


def key_of_ref(r):
    return r.object_id,r.version


@pytest.mark.pit
def test_event_age_and_material_age_separate(world):
    ledger,clock,source,seed,engine,policy=world
    started=clock.value-timedelta(days=2)
    evidence=receive(world,"明确事件实际起点",claim_kind="FACT",is_first_hand=True)
    a=assess(world,evidence,"SUPPORT",event_started_at=started)
    clock.advance(minutes=10)
    state=evaluate(world,"ages",assessment_refs=[vr(a)])
    value=ledger.get(*key_of_ref(state.clock_ref))
    assert value.event_age_seconds>value.observed_age_seconds>value.time_since_last_material_update_seconds
    assert value.event_started_at==started


@pytest.mark.pit
def test_new_policy_does_not_backfill_history(world):
    ledger,clock,source,seed,engine,policy=world
    receive(world)
    evaluate(world,"old-policy")
    cutoff=clock()
    before=ledger.replay(cutoff)
    later=engine.policy(version=2,rapid_min_sources=1,mainstream_min_sources=2,crowded_min_sources=3,acceleration_factor=1)
    args=(vr(latest(ledger,clock)),vr(later))
    with pytest.raises(ValueError,match="STATE_REFERENCE"):
        engine.evaluate(*args,request_key="too-early",as_of=cutoff)
    state=engine.evaluate(*args,request_key="new-policy",as_of=clock())
    assert state.narrative_state=="RAPID_DIFFUSION" and state.policy_version=="STATE_POLICY:2"
    assert ledger.replay(cutoff)==before


def test_recompute_idempotency_and_expected_version(world):
    ledger,clock,source,seed,engine,policy=world
    e=receive(world,"一手事实",claim_kind="FACT",is_first_hand=True)
    a=assess(world,e,"SUPPORT")
    event=latest(ledger,clock)
    kwargs=dict(request_key="retry",as_of=clock(),assessment_refs=[vr(a)])
    first=engine.evaluate(vr(event),vr(policy),**kwargs)
    for _ in range(10):
        assert engine.evaluate(vr(event),vr(policy),**kwargs)==first
    assert len(engine.pending(as_of=clock()))==1
    with pytest.raises(ValueError,match="EXPECTED_VERSION"):
        engine.evaluate(vr(event),vr(policy),request_key="stale",as_of=clock())


@pytest.mark.parametrize("dimension,previous,new",[("FACT","OFFICIALLY_CONFIRMED","UNVERIFIED"),("FACT","UNVERIFIED","HYPE"),("NARRATIVE","UNKNOWN","FAKE"),("PRICING","UNKNOWN","FAKE")])
def test_forbidden_table_and_unknown_state_fail_closed(dimension,previous,new):
    with pytest.raises(ValueError,match="TRANSITION_FORBIDDEN"):
        check_transition(dimension,previous,new)


def test_explicit_tables_cover_every_pair():
    for dimension,table in ALLOWED.items():
        for state,targets in table.items():
            assert not targets & FORBIDDEN[dimension][state]
            assert targets | FORBIDDEN[dimension][state]==set(table)


@pytest.mark.parametrize("model",list(SCHEMAS))
def test_phase3_json_schema(model):
    assert SCHEMAS[model].model_json_schema()["type"]=="object"


def test_atomic_state_rollback(world):
    ledger,clock,source,seed,engine,policy=world
    receive(world)
    before=ledger.replay(clock())
    def fault(stage):
        if stage=="after_state":
            raise RuntimeError("模拟状态事务崩溃")
    ledger.fault=fault
    with pytest.raises(RuntimeError):
        evaluate(world,"crash")
    assert ledger.replay(clock())==before
