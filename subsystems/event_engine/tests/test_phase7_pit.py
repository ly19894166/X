"""研究知识与完成时间隔离；不修改Phase1–6 PIT测试。"""
import json
import pytest
from test_phase7_research import seed,w,run,rebuild,mixed,second_company
from test_phase6_review_a1 import revise
from test_phase6_history import other_event
from xevent.research.packet import vr
from xevent.research.provider import MockModelProvider,mock_output
from xevent.research.contracts import ResearchPacket
from xevent.ledger.contracts import RawObservation,EventSeed
from xevent.ledger.store import ref
from xevent.contracts.common import TypeAdapter,UTCDateTime,PITQuery
from xevent.states.engine import StateEngine
from xevent.exposures.fixture import disclose,exposure,metric

pytestmark=pytest.mark.pit


def test_completion_at_1452_not_visible_at_1451(w):
    w['clock'].value=TypeAdapter(UTCDateTime).validate_python('2026-09-08T14:50:00+08:00')
    w['packet']=w['research'].packet('TIMED',vr(w['history']),vr(w['model']),as_of=w['clock']())
    def respond(kind,data):
        w['clock'].value=max(w['clock'].value,TypeAdapter(UTCDateTime).validate_python('2026-09-08T14:52:00+08:00'))
        return mock_output(kind,data)
    result,_=run(w,MockModelProvider(respond))
    mid=TypeAdapter(UTCDateTime).validate_python('2026-09-08T14:51:00+08:00')
    assert result.started_at<mid<result.completed_at<=result.available_at
    assert not w['ledger'].history(as_of=mid,kind='ModelResult')
    assert not w['ledger'].history(as_of=mid,kind='AnalysisRun')
    assert w['ledger'].history(as_of=w['clock'](),kind='AnalysisRun')==[result]


@pytest.mark.parametrize('target,reason',[('event','EVENT_RECOMPUTE_REQUIRED'),('impact','IMPACT_RECOMPUTE_REQUIRED'),
    ('resolution','RESOLUTION_RECOMPUTE_REQUIRED'),('ex','EXPOSURE_RECOMPUTE_REQUIRED'),
    ('company','COMPANY_RECOMPUTE_REQUIRED'),('state','EVENT_STATE_RECOMPUTE_REQUIRED')])
def test_current_freshness_cannot_be_overruled_by_model(w,target,reason):
    cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    revise(w,w[target])
    result,p=run(w)
    assert reason in result.hold_reasons and result.final_choice=='HOLD' and not p.calls
    assert w['ledger'].replay(cutoff)==before


def test_new_evidence_cannot_reuse_old_cached_current_research(w):
    old,p=run(w)
    before=w['ledger'].replay(w['packet'].as_of)
    w['ledger'].ingest(RawObservation(source_ref=vr(w['source']),locator='fixture:new-event-evidence',
        raw='新的实质证据'.encode(),first_seen_at=w['clock'](),collected_at=w['clock'](),content_version='1',claim_kind='FACT'),
        EventSeed(event_id=w['event'].object_id,title_zh=w['event'].title_zh,dna=w['event'].dna))
    result,_=run(w,p,identity='AFTER_EVIDENCE')
    assert result.final_choice=='HOLD' and len(p.calls)==2
    assert old.final_choice=='TARGET' and w['ledger'].replay(w['packet'].as_of)==before


def test_packet_changed_input_changes_cache_key(w):
    old,p=run(w)
    rebuild(w)
    new,_=run(w,p,identity='NEW_GRAPH')
    assert len(p.calls)==4 and new.primary_result_ref!=old.primary_result_ref
    a=w['ledger'].get(old.primary_result_ref.object_id,1); b=w['ledger'].get(new.primary_result_ref.object_id,1)
    assert a.cache_key!=b.cache_key


def test_historical_research_separate_cache_and_no_backdated_result(w):
    original=w['packet']; old,p=run(w)
    revise(w,w['impact'])
    historical=w['research'].packet('HISTORICAL',vr(w['history']),vr(w['model']),as_of=original.as_of,research_mode='HISTORICAL_REPLAY')
    assert historical.available_at>original.as_of and historical.packet_hash!=original.packet_hash
    w['packet']=historical
    replay,_=run(w,p,identity='HIST_RUN')
    assert replay.research_mode=='HISTORICAL_REPLAY' and replay.final_choice=='TARGET' and len(p.calls)==4
    assert replay.available_at>replay.as_of
    assert not w['ledger'].history(as_of=original.as_of,kind='AnalysisRun')
    now=w['clock']()
    model_result=w['ledger'].get(replay.primary_result_ref.object_id,1)
    for obj in (historical,replay,model_result):
        assert not obj.is_visible(PITQuery(as_of=now,mode='LIVE_FORWARD'))
        assert obj.is_visible(PITQuery(as_of=now,mode='OBSERVED_REPLAY'))


def test_later_numeric_restatement_only_changes_new_packet(w):
    old_packet=w['packet']; old_metric=w['metric']
    cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    d=disclose(w,2); w['ex']=w['master'].exposure(2,exposure(w,d,effective_to=None))
    newer=w['master'].metric(2,metric(w['ex'],numerator=20.0))
    rebuild(w)
    assert vr(newer) in w['packet'].metric_refs and vr(old_metric) not in w['packet'].metric_refs
    assert vr(old_metric) in old_packet.metric_refs
    assert w['packet'].packet_hash!=old_packet.packet_hash and w['ledger'].replay(cutoff)==before


def test_future_input_or_return_cannot_enter_old_packet(w):
    cutoff=w['packet'].as_of
    evidence=w['ledger'].ingest(RawObservation(source_ref=vr(w['source']),locator='fixture:future-return',
        raw='后来用户说次日收益赚钱'.encode(),first_seen_at=w['clock'](),collected_at=w['clock'](),content_version='1'),w['seed'])
    assert evidence.available_at>cutoff
    data=w['research'].provider_data(w['packet'])
    assert '后来用户说次日收益赚钱' not in json.dumps(data,ensure_ascii=False)
    with pytest.raises(ValueError):
        w['research'].packet('TOO_EARLY',vr(w['history']),vr(w['model']),as_of=w['event'].available_at)


def test_alt_cannot_steal_unrelated_event_path(w):
    event,res,_=other_event(w,'UNRELATED')
    from xevent.graph.fixture import request
    h=w['graph'].build('UNRELATED_GRAPH',1,request(w,event_ref=vr(event),resolution_refs=[vr(res)],
        exposure_refs=[vr(w['ex']),vr(w['negative'])]))
    foreign=h.path_refs[0]
    def respond(kind,data):
        body=mock_output(kind,data)
        if kind=='PRIMARY':
            alt={**body['target'],'hypothesis_id':'FOREIGN_ALT','type':'ALT','supporting_path_refs':[ref(foreign)]}
            body['alternatives']=[alt]
        return body
    result,_=run(w,MockModelProvider(respond))
    assert 'INVALID_REFERENCE' in result.hold_reasons


def test_contradicted_event_requires_hold_and_preserves_old_run(w):
    old,_=run(w); cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    se=StateEngine(w['ledger']); policy=se.policy()
    a=se.assess(vr(w['event']),vr(w['event_evidence']),assessment_key='p7-counter',kind='COUNTEREVIDENCE',
        quoted_span='明确宣布铜供应减少',reviewed_by='虚构核验者',interpretation_zh='虚构明确反证')
    se.evaluate(vr(w['event']),vr(policy),request_key='p7-counter',as_of=w['clock'](),assessment_refs=[vr(a)])
    result,p=run(w,identity='AFTER_COUNTER')
    assert result.final_choice=='HOLD' and not p.calls
    assert 'EVENT_FACT_REVIEW_REQUIRED' in result.hold_reasons
    assert w['ledger'].replay(cutoff)==before and old.final_choice=='TARGET'


def test_new_fact_while_model_running_checked_before_publication(w):
    once=[False]
    def respond(kind,data):
        if not once[0]:
            once[0]=True
            # 模拟外部在研究期间发布，但避免跨线程持有Ledger互斥锁；在主线程fault hook触发。
        return mock_output(kind,data)
    changed=[False]
    def fault(stage):
        if stage=='after_model_result' and not changed[0]:
            changed[0]=True; revise(w,w['impact'])
    w['ledger'].fault=fault
    result,_=run(w,MockModelProvider(respond))
    assert result.final_choice=='NULL' and 'IMPACT_RECOMPUTE_REQUIRED' in result.hold_reasons


def test_seventy_same_origin_reposts_do_not_multiply_confidence(w):
    event,res,ev=other_event(w,'SEVENTY',origin=w['event_evidence'],repeats=70)
    se=StateEngine(w['ledger']); policy=se.policy()
    state=se.evaluate(vr(event),vr(policy),request_key='seventy',as_of=w['clock']())
    event=w['ledger'].get(state.event_ref.object_id,state.event_ref.version)
    from xevent.ontology.contracts import ImpactSpec
    impact=w['ontology_engine'].impact('SEVENTY_CURRENT_PRICE',1,ImpactSpec(event_ref=vr(event),variable_type='PRICE',target_object='COPPER',
        direction='UP',geography='GLOBAL',observation_kind='HYPOTHESIS',premise_refs=[vr(ev)],
        mechanism_zh='供应可能影响产出价格',uncertainty_zh='转述不是独立确认'))
    res=w['ontology_engine'].resolve(vr(impact),vr(w['ontology']),as_of=w['clock'](),request_key='seventy-final')
    w['event']=event; w['resolution']=res
    from xevent.graph.fixture import request
    h=w['graph'].build('SEVENTY_GRAPH',1,request(w,event_ref=vr(event),resolution_refs=[vr(res)],exposure_refs=[vr(w['ex']),vr(w['negative'])]))
    w['packet']=w['research'].packet('SEVENTY_PACKET',vr(h),vr(w['model']),as_of=w['clock']())
    coverage=w['ledger'].get(w['packet'].search_coverage_ref.object_id,1)
    assert coverage.origin_count==1 and coverage.independent_source_count in (None,1)
    result,_=run(w)
    assert w['ledger'].get(result.primary_result_ref.object_id,1).primary.target.confidence_band=='LOW'


def test_replay_twice_deterministic(w):
    result,_=run(w); cutoff=w['clock']()
    assert w['ledger'].replay(cutoff)==w['ledger'].replay(cutoff)
    assert w['research'].report(vr(result))==w['research'].report(vr(result))
