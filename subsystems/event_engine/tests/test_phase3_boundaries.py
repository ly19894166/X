from pathlib import Path
from datetime import timedelta
import json

import pytest

from test_phase2_ledger import setup_ledger, obs
from test_phase3_states import world,receive,assess,evaluate,latest,vr
from xevent.contracts import Source
from xevent.contracts.common import ObservationWindow
from xevent.ledger.store import Ledger
from xevent.states.engine import StateEngine


def test_chinese_cli_fixture_and_schema(tmp_path,capsys):
    from xevent.cli import main
    fixture=Path(__file__).parents[1]/"configs"/"phase3_states.zh-CN.json"
    db=tmp_path/"state-demo.sqlite"
    assert main(["state-fixture","--fixture",str(fixture),"--db",str(db)])==0
    result=json.loads(capsys.readouterr().out)
    assert [r["事实"] for r in result["时间线"]]==["UNVERIFIED","OFFICIALLY_CONFIRMED","CONTRADICTED"]
    assert main(["schema","--model","EventClock"])==0
    assert json.loads(capsys.readouterr().out)["title"]=="EventClock"
    assert main(["state-fixture","--fixture",str(fixture),"--db",str(db)])==2


@pytest.mark.parametrize("kind",["OFFICIAL_CONFIRMATION","IMPLEMENTATION"])
def test_intent_cannot_become_fact(world,kind):
    evidence=receive(world,"只是意图",claim_kind="INTENT",is_first_hand=True)
    with pytest.raises(ValueError,match="FACT_KIND"):
        assess(world,evidence,kind,authority_scope_zh="虚构机构")
    assert not world[0].history(as_of=world[1](),kind="EvidenceAssessment")


def test_official_tier_and_quote_required(world):
    ledger,clock,source,seed,engine,policy=world
    nonofficial=ledger.register_source(Source.model_validate({**source.model_dump(),"object_id":"MEDIA","source_id":"MEDIA","tier":"S1"}))
    evidence=ledger.ingest(obs(clock,nonofficial,"媒体称已获官方确认",claim_kind="FACT",is_first_hand=True),seed)
    with pytest.raises(ValueError,match="OFFICIAL_PROOF"):
        assess(world,evidence,"OFFICIAL_CONFIRMATION",authority_scope_zh="自称官方")
    with pytest.raises(ValueError,match="ASSESS_PROOF"):
        engine.assess(vr(latest(ledger,clock)),vr(evidence),assessment_key="fakequote",kind="SUPPORT",
            quoted_span="原文不存在",reviewed_by="fixture",interpretation_zh="不能伪造")


def test_new_primary_triggers_research_without_automatic_fact_upgrade(world):
    receive(world,"新增一手材料尚待主张核验",is_first_hand=True)
    state=evaluate(world,"primary")
    assert state.fact_state=="UNVERIFIED" and state.priority=="P1"
    assert "NEW_PRIMARY_EVIDENCE" in world[4].pending(as_of=world[1]())[0].trigger_reasons


def test_unverified_r5_is_trigger_not_automatic_fact_grade(world):
    ledger,clock,source,seed,engine,policy=world
    source=ledger.register_source(Source.model_validate({**source.model_dump(),"version":2,"identity_status":"UNVERIFIED"}))
    world=(ledger,clock,source,seed,engine,policy)
    fields={"retracted":"false"}
    receive(world,json.dumps(fields),structured_fields=fields,structured_basis="SOURCE_STRUCTURED",is_first_hand=True)
    evaluate(world,"unverified")
    fields["retracted"]="true"
    receive(world,json.dumps(fields),version="2",change_type="EDIT",structured_fields=fields,structured_basis="SOURCE_STRUCTURED",is_first_hand=True)
    state=evaluate(world,"unverified-r5")
    assert state.fact_state=="UNVERIFIED" and state.priority=="P0"
    assert any(t.outcome=="HOLD" and t.dimension=="FACT" for t in ledger.history(as_of=clock(),kind="StateTransition"))


def test_partial_claim_is_not_second_full_independent_confirmation(world):
    ledger,clock,source,seed,engine,policy=world
    first=receive(world,"完整主张支持",claim_kind="FACT",is_first_hand=True)
    full=assess(world,first,"SUPPORT")
    second_source=ledger.register_source(Source.model_validate({**source.model_dump(),"source_id":"PARTIAL_SOURCE","object_id":"PARTIAL_SOURCE"}))
    second=ledger.ingest(obs(clock,second_source,"仅部分主张已核验",claim_kind="FACT",is_first_hand=True),seed)
    partial=assess(world,second,"PARTIAL")
    state=evaluate(world,"partial-is-not-full",assessment_refs=[vr(full),vr(partial)])
    assert state.fact_state=="PARTIALLY_CONFIRMED"


@pytest.mark.pit
def test_unresolved_contradiction_cannot_select_later_favorable_claim(world):
    ledger,clock,source,seed,engine,policy=world
    denial=receive(world,"否认",claim_kind="FACT",is_first_hand=True)
    negative=assess(world,denial,"OFFICIAL_DENIAL",authority_scope_zh="负责机构")
    evaluate(world,"negative",assessment_refs=[vr(negative)])
    cutoff=clock()
    before=ledger.replay(cutoff)
    clock.advance(minutes=10)
    new=receive(world,"后来有利证据但尚未解释矛盾",locator="fixture:positive",claim_kind="FACT",is_first_hand=True)
    positive=assess(world,new,"OFFICIAL_CONFIRMATION",authority_scope_zh="负责机构")
    assert evaluate(world,"still-conflicted",assessment_refs=[vr(positive)]).fact_state=="CONTRADICTED"
    resolved=assess(world,new,"RESOLUTION",resolves_refs=[vr(negative)])
    assert evaluate(world,"resolved",assessment_refs=[vr(resolved)]).fact_state=="OFFICIALLY_CONFIRMED"
    assert ledger.replay(cutoff)==before


@pytest.mark.pit
def test_missing_and_mixed_prices_are_unknown_with_security_details(world):
    ledger,clock,source,seed,engine,policy=world
    evidence=receive(world,"价格观察fixture")
    observations=[]
    for security,price in (("000001","NO_REACTION"),("000002","OVERTRADED")):
        observations.append(engine.price(vr(latest(ledger,clock)),observation_key=security,security_id=security,
            window=ObservationWindow(start=clock.value-timedelta(minutes=5),end=clock()),observation=price,
            evidence_refs=[vr(evidence)],basis_zh="虚构价格"))
    assert evaluate(world,"mixed",price_refs=[vr(p) for p in observations]).pricing_state=="UNKNOWN"
    assert evaluate(world,"one",price_refs=[vr(observations[0])]).pricing_state=="NO_REACTION"
    assert evaluate(world,"missing").pricing_state=="UNKNOWN"
    assert len(ledger.history(as_of=clock(),kind="SecurityPriceObservation"))==2


def test_crowded_rumor_and_time_decay_never_invalidates_fact(world):
    ledger,clock,source,seed,engine,policy=world
    policy=engine.policy(version=2,rapid_min_sources=2,mainstream_min_sources=3,crowded_min_sources=3)
    world=(*world[:5],policy)
    original=receive(world,claim_kind="RUMOR")
    for n in range(2):
        s=ledger.register_source(Source.model_validate({**source.model_dump(),"object_id":f"M{n}","source_id":f"M{n}"}))
        ledger.ingest(obs(clock,s,f"转发{n}",origin_ref=vr(original),claim_kind="RUMOR"),seed)
    state=evaluate(world,"crowded")
    assert state.narrative_state=="CROWDED" and state.fact_state=="UNVERIFIED"
    clock.advance(days=10)
    state=evaluate(world,"decay")
    assert state.narrative_state=="DECAY" and state.fact_state=="UNVERIFIED"


@pytest.mark.pit
def test_cross_asset_trigger_is_fixture_only_and_not_fact(world):
    ledger,clock,source,seed,engine,policy=world
    e=receive(world,"跨资产fixture")
    p=engine.price(vr(latest(ledger,clock)),observation_key="cross",security_id="FX_FIXTURE",
        window=ObservationWindow(start=clock.value-timedelta(minutes=1),end=clock()),observation="INITIAL_REACTION",
        evidence_refs=[vr(e)],basis_zh="虚构跨资产",cross_asset_confirmed=True)
    state=evaluate(world,"cross",price_refs=[vr(p)])
    assert state.fact_state=="UNVERIFIED"
    assert "CROSS_ASSET_CONFIRMATION" in engine.pending(as_of=clock())[-1].trigger_reasons


@pytest.mark.pit
def test_state_commit_crash_recovery_keeps_original_visibility(world):
    ledger,clock,source,seed,engine,policy=world
    receive(world)
    event=latest(ledger,clock)
    args=dict(request_key="commit-crash",as_of=clock())
    def fault(stage):
        if stage=="after_commit":
            raise RuntimeError("提交后崩溃")
    ledger.fault=fault
    with pytest.raises(RuntimeError):
        engine.evaluate(vr(event),vr(policy),**args)
    cutoff=clock()
    assert not ledger.history(as_of=cutoff,kind="StateTransition")
    ledger.close()
    clock.advance(minutes=1)
    reopened=Ledger(ledger.path,clock=clock)
    result=StateEngine(reopened).evaluate(vr(event),vr(policy),**args)
    assert result.available_at>cutoff
    assert not reopened.history(as_of=cutoff,kind="StateTransition")
    assert len(reopened.history(as_of=clock(),kind="EventStateSnapshot"))==1
    reopened.close()
