"""Phase 8 A1 additions only; original 656 cases remain unchanged."""
import pytest
from test_phase8_pricing import seed,w,get,assess,replace_ref,ENVELOPE_FIELDS
from xevent.pricing.contracts import *
from xevent.pricing.freshness import semantic_scope
from xevent.ledger.store import ref,digest
from xevent.research.packet import vr


def copy_input(w,obj,identity,mode=None,version=1,**changes):
    payload=obj.model_dump(mode='json')
    for k in ENVELOPE_FIELDS | {'as_of','pricing_mode'}: payload.pop(k,None)
    payload.update(changes)
    return w['pricing'].publish(type(obj),identity,payload,as_of=w['clock'](),version=version,
        pricing_mode=mode or obj.pricing_mode)


def input_object(w,kind):
    return {'provider':w['provider'],'context':w['context'],'composition':w['INDUSTRY_composition'],
        'adjustment':w['adjustments'][w['security'].object_id],
        'session':w['sessions'][w['security'].object_id],'policy':w['policy'],
        'observation':get(w,w['request'].price_refs[-1])}[kind]


@pytest.mark.pit
@pytest.mark.parametrize('kind,reason',[
    ('provider','PROVIDERQUALIFICATION_RECOMPUTE_REQUIRED'),('context','PRICINGCONTEXT_RECOMPUTE_REQUIRED'),
    ('composition','BENCHMARKCOMPOSITION_RECOMPUTE_REQUIRED'),('adjustment','ADJUSTMENTBASIS_RECOMPUTE_REQUIRED'),
    ('session','MARKETSESSION_RECOMPUTE_REQUIRED'),('policy','PRICINGPOLICY_RECOMPUTE_REQUIRED')])
def test_new_id_same_scope_invalidates_current_and_build(w,kind,reason):
    old=assess(w); cutoff=w['clock'](); replay=w['ledger'].replay(cutoff)
    original=input_object(w,kind)
    changes={'qualification_status':'PROVIDER_HOLD','timestamp_verified':False} if kind=='provider' else {}
    new=copy_input(w,original,'A1_NEW_'+kind,**changes)
    assert new.object_id!=original.object_id and semantic_scope(new)==semantic_scope(original)
    current=w['pricing'].current(vr(old),as_of=w['clock'](),pricing_mode='ENGINEERING_FIXTURE')
    assert reason in current['recompute_reasons'] and current['current_remaining_edge']=='HOLD'
    assert reason in assess(w,'NEW_ASSESSMENT').hold_reasons
    assert w['pricing'].current(vr(old),as_of=cutoff,pricing_mode='ENGINEERING_FIXTURE')['freshness']=='AS_RECORDED'
    assert w['ledger'].replay(cutoff)==replay


@pytest.mark.pit
@pytest.mark.parametrize('origin_mode,new_mode',[('MOCK_FORWARD','HISTORICAL_REPLAY'),('HISTORICAL_REPLAY','MOCK_FORWARD')])
@pytest.mark.parametrize('kind',['provider','context','composition','adjustment','session','policy','observation'])
def test_freshness_does_not_cross_modes(w,kind,origin_mode,new_mode):
    original=input_object(w,kind)
    own=original if origin_mode=='MOCK_FORWARD' and kind!='observation' else copy_input(w,original,'OWN_'+kind,mode=origin_mode)
    w['request']=replace_ref(w['request'],original,own)
    if kind in ('provider','adjustment','session'):
        for r in tuple(w['request'].price_refs):
            price=get(w,r)
            field={'provider':'provider_ref','adjustment':'adjustment_ref','session':'session_ref'}[kind]
            updated=copy_input(w,price,'OWN_PRICE_'+r.object_id,mode=origin_mode,**{field:ref(own)})
            w['request']=replace_ref(w['request'],price,updated)
    if kind=='composition':
        bm=next(get(w,r) for r in w['request'].benchmark_refs if get(w,r).benchmark_role=='INDUSTRY')
        b=w['pricing'].benchmark('OWN_BM',price_refs=bm.price_refs,composition_ref=vr(own),benchmark_role='INDUSTRY',
            as_of=w['clock'](),pricing_mode=origin_mode)
        w['request']=replace_ref(w['request'],bm,b)
    old=assess(w,pricing_mode=origin_mode)
    before=w['pricing'].current(vr(old),as_of=w['clock'](),pricing_mode=origin_mode)
    assert before['freshness']=='AS_RECORDED'
    foreign=copy_input(w,own,'FOREIGN_'+kind,mode=new_mode)
    now=w['pricing'].current(vr(old),as_of=w['clock'](),pricing_mode=origin_mode)
    assert now['recompute_reasons']==before['recompute_reasons']
    assert now['freshness']==before['freshness']
    after=assess(w,'AFTER_FOREIGN',pricing_mode=origin_mode)
    assert after.hold_reasons==old.hold_reasons
    assert semantic_scope(foreign)!=semantic_scope(own)


def publish_novelty(w,classification,identity):
    ev=w['event'].evidence_refs[-1]
    data=dict(classification=classification,evidence_ref=ref(ev),evidence_refs=[ref(ev)],
        reason_codes=['A1_REVIEWED_RECLASSIFICATION'],status='READY')
    def write(conn,view,batch):
        w['ledger']._put(conn,batch,'NoveltyDecision',identity,1,data,[ref(ev)])
    w['ledger']._write(identity,digest(data),write)
    return w['ledger'].get(identity,1)


@pytest.mark.pit
def test_novelty_reclassification_invalidates_current_only(w):
    publish_novelty(w,'R4','A1_NOV_R4')
    old=assess(w)
    assert old.novelty=='R4' and old.remaining_edge=='POSITIVE'
    cutoff=w['clock'](); replay=w['ledger'].replay(cutoff)
    publish_novelty(w,'R1','A1_NOV_R1')
    current=w['pricing'].current(vr(old),as_of=w['clock'](),pricing_mode=old.pricing_mode)
    assert current['current_remaining_edge']=='HOLD'
    assert 'NOVELTY_RECOMPUTE_REQUIRED' in current['recompute_reasons']
    assert w['pricing'].current(vr(old),as_of=cutoff,pricing_mode=old.pricing_mode)['freshness']=='AS_RECORDED'
    assert w['ledger'].replay(cutoff)==replay
    newer=assess(w,'NOV_UPDATED')
    assert newer.novelty=='R1' and newer.remaining_edge!='POSITIVE'


@pytest.mark.parametrize('other_path',[False,True])
def test_next_buyer_bound_to_assessed_path(w,other_path):
    from xevent.ontology.engine import OntologyEngine
    from xevent.ontology.contracts import ImpactSpec
    from xevent.graph.engine import TransmissionGraph
    from xevent.graph.fixture import request as graph_request
    from xevent.research.provider import MockModelProvider,mock_output
    ontology=OntologyEngine(w['ledger'])
    spec={k:v for k,v in w['impact'].model_dump(mode='json').items() if k in ImpactSpec.model_fields}
    spec['mechanism_zh']='另一项虚构经济机制，独立固定候选'
    impact=ontology.impact('A1_OTHER_IMPACT',1,ImpactSpec.model_validate(spec))
    resolution=ontology.resolve(vr(impact),vr(w['ontology']),as_of=w['clock'](),request_key='A1_OTHER_RES')
    history=TransmissionGraph(w['ledger']).build('A1_TWO_PATHS',1,graph_request(w,
        resolution_refs=[vr(w['resolution']),vr(resolution)]))
    packet=w['research'].packet('A1_TWO_PACKET',vr(history),vr(w['model']),as_of=w['clock']())
    def respond(role,data):
        out=mock_output(role,data)
        if role=='PRIMARY': out['target']['confidence_band']='HIGH'
        return out
    run=w['research'].run('A1_TWO_RUN',vr(packet),MockModelProvider(respond))
    primary=get(w,run.primary_result_ref).primary
    path=get(w,primary.target.supporting_path_refs[0])
    w['request']=w['request'].model_copy(update={'analysis_ref':vr(run),'path_ref':vr(path)})
    w['path']=path; w['packet']=packet
    paths=[get(w,r) for r in packet.path_refs]
    other=next(p for p in paths if vr(p)!=vr(w['path']) and p.security_ref==w['path'].security_ref and p.world=='ECONOMIC')
    buyer=w['request'].next_buyers[0].model_copy(update={'supporting_path_refs':(vr(other if other_path else w['path']),)})
    a=assess(w,next_buyers=(buyer,))
    result=get(w,a.next_buyer_refs[0])
    if other_path:
        assert result.hypothesis_status=='WEAK' and 'NEXT_BUYER_MECHANISM_MISMATCH' in result.reason_codes_buyer
        assert a.remaining_edge not in ('POSITIVE','STRONG')
    else:
        assert result.hypothesis_status=='SUPPORTED' and a.remaining_edge=='POSITIVE'


@pytest.mark.pit
@pytest.mark.parametrize('kind',['provider','context','composition','adjustment','session','policy','observation'])
def test_same_id_foreign_mode_revision_does_not_pollute_forward(w,kind):
    old=assess(w,pricing_mode='MOCK_FORWARD')
    obj=input_object(w,kind)
    copy_input(w,obj,obj.object_id,mode='HISTORICAL_REPLAY',version=obj.version+1)
    now=w['pricing'].current(vr(old),as_of=w['clock'](),pricing_mode='MOCK_FORWARD')
    assert now['freshness']=='AS_RECORDED'
    after=assess(w,'AFTER_SAME_ID',pricing_mode='MOCK_FORWARD')
    assert after.hold_reasons==old.hold_reasons


@pytest.mark.pit
def test_unrelated_evidence_novelty_does_not_invalidate(w):
    old=assess(w)
    w['event']=w['event'].model_copy(update={'evidence_refs':(vr(w['review_evidence']),)})
    publish_novelty(w,'R1','A1_UNRELATED_NOV')
    assert w['pricing'].current(vr(old),as_of=w['clock'](),pricing_mode=old.pricing_mode)['freshness']=='AS_RECORDED'


def test_session_explicit_scope_ignores_mutable_calendar_metadata(w):
    original=w['sessions'][w['security'].object_id]
    a=original.model_copy(update={'session_scope':'A_SHARE_PRIMARY'})
    b=a.model_copy(update={'object_id':'OTHER_SESSION_ID','calendar_version':'REVISED','timezone':'UTC',
                          'utc_offset_minutes':0,'intervals':()})
    assert semantic_scope(a)==semantic_scope(b)


def test_forward_fixtures_are_not_real_forward(w):
    original=w['policy']
    assert semantic_scope(original)!=semantic_scope(original.model_copy(update={'pricing_mode':'REAL_FORWARD'}))


@pytest.mark.pit
@pytest.mark.parametrize('empty',[False,True])
def test_ambiguous_new_session_scope_fails_closed(w,empty):
    old=assess(w); cutoff=w['clock']()
    original=w['sessions'][w['security'].object_id]
    copy_input(w,original,'A1_CHANGED_SESSION_SCOPE',intervals=[] if empty else [x.model_dump(mode='json') for x in original.intervals[:1]])
    current=w['pricing'].current(vr(old),as_of=w['clock'](),pricing_mode=old.pricing_mode)
    assert 'MARKETSESSION_RECOMPUTE_REQUIRED' in current['recompute_reasons']
    assert current['current_remaining_edge']=='HOLD'
    assert w['pricing'].current(vr(old),as_of=cutoff,pricing_mode=old.pricing_mode)['freshness']=='AS_RECORDED'
