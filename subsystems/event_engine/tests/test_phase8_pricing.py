"""Phase8新增业务与契约测试；不改变原582项。"""
import json
import shutil
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from xevent.pricing.fixture import prepare, request, observation
from xevent.pricing.contracts import *
from xevent.pricing.engine import PricingEngine, ENVELOPE_FIELDS
from xevent.pricing.calculations import classify_dimensions, price_return, volume_multiple
from xevent.ledger.store import Ledger, ref
from xevent.research.packet import vr
from xevent.research.engine import ResearchEngine
from xevent.research.provider import MockModelProvider, mock_output
from xevent.exposures.fixture import FixtureClock

CONFIGS=Path(__file__).parents[1]/'configs'


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    path=tmp_path_factory.mktemp('p8-seed')/'base.sqlite'
    data=prepare(path,CONFIGS); data['request']=request(data)
    data['ledger'].close()
    return path,data,data['clock'].value.isoformat()


@pytest.fixture
def w(seed,tmp_path):
    path,data,stamp=seed
    copy=tmp_path/'pricing.sqlite'; shutil.copyfile(path,copy)
    clock=FixtureClock(stamp); ledger=Ledger(copy,clock=clock)
    result={**data,'clock':clock,'ledger':ledger,'pricing':PricingEngine(ledger),'research':ResearchEngine(ledger),
        'adjustments':dict(data['adjustments']),'sessions':dict(data['sessions'])}
    yield result
    ledger.close()


def pub(w,cls,identity,version=1,**fields):
    return w['pricing'].publish(cls,identity,dict(observed_at=w['clock']().isoformat(),
        provenance_zh='虚构工程核验记录',**fields),as_of=w['clock'](),version=version)


def get(w,r):
    return w['ledger'].get(r.object_id,r.version)


def replace_ref(request,old,new):
    def visit(data):
        if isinstance(data,dict):
            if data==ref(old): return ref(new)
            return {k:visit(v) for k,v in data.items()}
        if isinstance(data,list): return [visit(v) for v in data]
        return data
    return PricingRequest.model_validate(visit(request.model_dump(mode='json')))


def revise(w,o,**changes):
    payload=o.model_dump(mode='json')
    for k in ENVELOPE_FIELDS|{'as_of','pricing_mode'}: payload.pop(k,None)
    if isinstance(o,MarketObservation):
        seen=w['clock'](); received=w['clock']()
        payload.update(first_seen_at=seen.isoformat(),received_at=received.isoformat(),
            staleness_seconds=(received-o.observed_at).total_seconds())
    payload.update(changes)
    return w['pricing'].publish(type(o),o.object_id,payload,as_of=w['clock'](),version=o.version+1,pricing_mode=o.pricing_mode)


def reprice(w,stock=None,industry=None,market=None):
    req=w['request']
    if stock is not None:
        old=get(w,req.price_refs[-1]); new=revise(w,old,value=100.0*(1+stock))
        req=replace_ref(req,old,new)
    for role,value in (('INDUSTRY',industry),('MARKET',market)):
        if value is None: continue
        bm=next(get(w,r) for r in req.benchmark_refs if get(w,r).benchmark_role==role)
        old=get(w,bm.price_refs[-1]); new=revise(w,old,value=100.0*(1+value))
        updated=w['pricing'].benchmark(bm.object_id,price_refs=[bm.price_refs[0],vr(new)],composition_ref=bm.composition_ref,
            benchmark_role=role,as_of=w['clock'](),version=bm.version+1)
        req=replace_ref(req,bm,updated)
    w['request']=req
    return req


def assess(w,identity='TEST',**changes):
    req=PricingRequest.model_validate({**w['request'].model_dump(),'as_of':w['clock'](),**changes})
    return w['pricing'].assess(identity,req)


def context(w,**outcomes):
    old=get(w,w['request'].context_ref)
    changes=[{**f.model_dump(), 'outcome':outcomes.get(f.dimension,f.outcome)} for f in old.findings]
    new=revise(w,old,findings=changes)
    w['request']=replace_ref(w['request'],old,new)
    return new


def new_analysis(w,choice='NULL',hold=False,mode='MOCK_FORWARD'):
    prompt,model=w['research'].configure('P8_OTHER_MODEL',max_output=2100)
    packet=w['research'].packet('P8_OTHER_PACKET',vr(w['history']),vr(model),as_of=w['clock'](),research_mode=mode)
    def respond(role,data):
        out=mock_output(role,data)
        if role=='PRIMARY':
            if hold: return '{}'
            out['selected_id']=choice
        return out
    return w['research'].run('P8_OTHER_ANALYSIS',vr(packet),MockModelProvider(respond))


def test_positive_simulation_is_not_formal_forward(w):
    a=assess(w)
    assert a.remaining_edge=='POSITIVE' and a.novelty=='R3'
    assert a.assessment_status=='ENGINEERING_ONLY' and not a.formal_positive_remaining_edge
    assert get(w,a.non_reaction_ref).investigation_status=='UNEXPLAINED_NON_REACTION'
    assert 'HOLD_MODEL_PROVIDER_LIVE' in a.hold_reasons
    assert a.remaining_edge!='STRONG'


def test_a_stock_and_industry_both_five_percent_not_high_price_in(w):
    reprice(w,stock=0.05,industry=0.05)
    a=assess(w); f=get(w,a.features_ref)
    assert f.raw_return==pytest.approx(0.05) and f.industry_relative_return==pytest.approx(0.0)
    assert a.price_in_band not in ('HIGH','VERY_HIGH')
    assert get(w,a.alternative_cause_ref).cause_status=='MULTI_CAUSE'
    assert not get(w,a.non_reaction_ref).recognition_gap


def test_b_two_percent_minus_negative_three_is_feature_not_causal(w):
    reprice(w,stock=0.02,industry=-0.03)
    a=assess(w); f=get(w,a.features_ref)
    assert f.industry_relative_return==pytest.approx(0.05)
    assert f.method=='SIMPLE_RELATIVE_RETURN_NOT_CAUSAL'
    assert a.price_in_band not in ('HIGH','VERY_HIGH') and f.beta is None


def test_c_pretrend_not_counted_as_event_return(w):
    old=get(w,w['request'].pre_price_refs[-1]); new=revise(w,old,value=108.0)
    w['request']=replace_ref(w['request'],old,new)
    reprice(w,stock=0.01)
    a=assess(w); f=get(w,a.features_ref)
    assert f.raw_return==pytest.approx(0.01) and f.pre_event_return==pytest.approx(0.08)
    assert 'PRE_EVENT_TREND_PRESENT' in get(w,a.alternative_cause_ref).reason_codes_cause


def test_d_nonreaction_unchecked_causes_does_not_mean_strong_edge(w):
    context(w,IMMATERIAL='UNKNOWN')
    a=assess(w)
    assert get(w,a.non_reaction_ref).triggered
    assert get(w,a.non_reaction_ref).investigation_status=='DATA_INSUFFICIENT'
    assert a.remaining_edge not in ('STRONG','POSITIVE')


@pytest.mark.parametrize('missing',['price_refs','benchmark_refs'])
def test_e_missing_core_data_holds(w,missing):
    a=assess(w,**{missing:()})
    assert a.price_in_band=='UNKNOWN' and a.remaining_edge=='HOLD'
    assert any(m.severity=='BLOCKING' for m in get(w,a.missing_dimensions_ref).items)


def test_f_sustained_crowded_joint_dimensions_not_single_score():
    f=SimpleNamespace(industry_relative_return=0.08,diffusion=SimpleNamespace(breadth_ratio=0.9),
        volume_ratio=5.0,amount_ratio=5.0,pre_event_return=0.0,volatility=0.07,breadth_delta=-0.1)
    args=dict(rules=PricingRules(),thesis='HIGH',novelty='R3',dissemination='YES',
        nonreaction=SimpleNamespace(recognition_gap=False),cause='CURRENT_EVENT_DOMINANT',remaining_diffusion='NO',
        sessions=4,counter=False)
    recognition,pi,crowd,edge,risk,_=classify_dimensions(f,buyer=False,**args)
    assert (recognition,pi,crowd,edge,risk)==('CONSENSUS','VERY_HIGH','EXTREME','NONE','EXTREME')
    assert classify_dimensions(f,buyer=True,**args)[3]=='THIN'


def test_g_known_dissemination_low_reaction_investigated(w):
    a=assess(w)
    assert a.recognition_state=='EARLY_RECOGNITION'
    assert get(w,a.non_reaction_ref).triggered
    assert get(w,a.non_reaction_ref).checks


def test_h_other_company_event_causes_multicause(w):
    reprice(w,stock=0.05)
    context(w,OTHER_EVENT='YES')
    a=assess(w)
    assert get(w,a.alternative_cause_ref).cause_status=='MULTI_CAUSE'
    assert a.remaining_edge not in ('STRONG','POSITIVE')


@pytest.mark.parametrize('change',[{'why_not_already_present':None},{'expected_trigger':None},
    {'failure_condition':None},{'why_not_already_present':'后续资金可能关注'}])
def test_i_unspecific_next_buyer_cannot_support_positive(w,change):
    buyer=w['request'].next_buyers[0].model_copy(update=change)
    a=assess(w,next_buyers=(buyer,))
    assert get(w,a.next_buyer_refs[0]).hypothesis_status=='WEAK'
    assert a.remaining_edge not in ('POSITIVE','STRONG')


def test_short_covering_not_assumed_for_a_share(w):
    buyer=w['request'].next_buyers[0].model_copy(update={'buyer_type':'SHORT_COVERING'})
    a=assess(w,next_buyers=(buyer,))
    assert get(w,a.next_buyer_refs[0]).hypothesis_status=='REJECTED'


@pytest.mark.parametrize('hold',[False,True])
def test_l_m_null_or_hold_cannot_be_rescued_by_prices(w,hold):
    reprice(w,stock=0.1)
    analysis=new_analysis(w,hold=hold)
    a=assess(w,analysis_ref=vr(analysis))
    assert a.remaining_edge=='HOLD' and not a.formal_positive_remaining_edge
    assert a.price_in_band=='UNKNOWN'
    assert get(w,vr(analysis)).final_choice==analysis.final_choice


def test_unknown_findings_not_default_zero(w):
    context(w,DISSEMINATION='UNKNOWN',OTHER_EVENT='UNKNOWN')
    a=assess(w)
    assert a.recognition_state=='UNKNOWN'
    assert a.price_in_band=='UNKNOWN'
    assert get(w,a.alternative_cause_ref).cause_status=='CAUSE_UNKNOWN'


def test_volume_same_clock_three_samples(w):
    a=assess(w); f=get(w,a.features_ref)
    assert f.volume_ratio==1.0 and f.amount_ratio==1.0
    assert f.volume_sample_n==3 and f.amount_sample_n==3


def test_incomplete_industry_denominator_not_hundred_percent(w):
    old=w['INDUSTRY_composition']; new=revise(w,old,expected_component_count=22,coverage_status='INCOMPLETE')
    bm=next(get(w,r) for r in w['request'].benchmark_refs if get(w,r).benchmark_role=='INDUSTRY')
    newbm=w['pricing'].benchmark(bm.object_id,price_refs=bm.price_refs,composition_ref=vr(new),benchmark_role='INDUSTRY',
        as_of=w['clock'](),version=2)
    w['request']=replace_ref(w['request'],bm,newbm)
    a=assess(w); f=get(w,a.features_ref)
    assert f.diffusion.breadth_ratio is None and f.diffusion.coverage=='INCOMPLETE'
    assert a.remaining_edge not in ('POSITIVE','STRONG')


def test_volume_does_not_become_actual_buyer_identity(w):
    a=assess(w)
    b=get(w,a.next_buyer_refs[0])
    assert b.epistemic_status=='HYPOTHESIS_NOT_OBSERVED_BUYER'
    assert b.hypothesis_status=='SUPPORTED'
    assert not a.formal_positive_remaining_edge


@pytest.mark.parametrize('field,value',[('holdings',['A']),('cost',1.0),('preference','喜欢'),
    ('yesterday_return',0.1),('execution_universe',['创业板']),('future_t1_return',0.05)])
def test_account_and_future_outcome_fields_rejected(w,field,value):
    data=w['request'].model_dump(); data[field]=value
    with pytest.raises(ValidationError): PricingRequest.model_validate(data)


@pytest.mark.parametrize('field,value',[('observation_type','CAUSAL_RETURN'),('value',float('nan')),
    ('unit','PERCENT'),('provider_timestamp','2025-01-01T00:00:00'),('value',-1.0)])
def test_market_invalid_contract_rejected(w,field,value):
    o=get(w,w['request'].price_refs[-1]); data=o.model_dump(); data[field]=value
    with pytest.raises(ValidationError): MarketObservation.model_validate(data)


def test_unknown_value_keeps_null(w):
    o=get(w,w['request'].price_refs[-1]); new=revise(w,o,value=None,quality_status='UNKNOWN',missing_reason='来源未提供')
    w['request']=replace_ref(w['request'],o,new)
    a=assess(w)
    assert get(w,a.features_ref).raw_return is None and a.remaining_edge=='HOLD'


def test_unproven_findings_rejected(w):
    fields=w['context'].model_dump(mode='json')
    for name in ENVELOPE_FIELDS|{'as_of','pricing_mode'}: fields.pop(name,None)
    fields['findings'][0]['quoted_span']='不存在的公司事件'
    with pytest.raises(ValueError,match='PROVENANCE'):
        w['pricing'].publish(PricingContext,'BAD_CONTEXT',fields,as_of=w['clock']())


def test_zero_baseline_not_division_by_zero(w):
    refs=[]
    for r in w['request'].volume_baseline_refs:
        old=get(w,r); new=revise(w,old,value=0.0); refs.append(vr(new))
    a=assess(w,volume_baseline_refs=refs)
    assert get(w,a.features_ref).volume_ratio is None


def test_json_schemas_roundtrip_complete_refs(w):
    a=assess(w)
    for cls in SCHEMAS.values(): assert cls.model_json_schema()['properties']
    for o in w['ledger'].history(as_of=w['clock']()):
        if isinstance(o,PricingEnvelope):
            assert type(o).model_validate_json(o.model_dump_json())==o
            declared={(r.object_id,r.version) for r in o.input_version_refs}
            from xevent.pricing.engine import fixed_refs
            payload=o.model_dump(mode='json')
            for field in ENVELOPE_FIELDS: payload.pop(field,None)
            assert all((r.object_id,r.version) in declared for r in fixed_refs(payload))
    assert a.available_at>=max(a.recorded_at,a.computed_at)
    assert all(r.available_at<=a.available_at for r in a.input_version_refs)


def test_deterministic_idempotence_and_no_upstream_changes(w):
    before={ref(o)['object_id']+':'+str(o.version):o.content_hash for o in w['ledger'].history(as_of=w['clock']())
        if not isinstance(o,PricingEnvelope)}
    req=w['request'].model_copy(update={'as_of':w['clock']()})
    a=w['pricing'].assess('SAME',req); b=w['pricing'].assess('SAME',req)
    assert a==b
    after={o.object_id+':'+str(o.version):o.content_hash for o in w['ledger'].history(as_of=w['clock']())
        if not isinstance(o,PricingEnvelope)}
    assert before==after


def test_transaction_failure_no_partial_pricing(w):
    before=w['ledger'].replay(w['clock']())
    def fault(stage):
        if stage=='after_pricing_assessment': raise RuntimeError('ROLLBACK')
    w['ledger'].fault=fault
    with pytest.raises(RuntimeError): assess(w)
    w['ledger'].fault=lambda _:None
    assert w['ledger'].replay(w['clock']())==before


def test_no_socket_and_no_provider_invocation(w,monkeypatch):
    import socket
    def fail(*args,**kwargs): raise AssertionError('NO_NETWORK')
    monkeypatch.setattr(socket,'socket',fail)
    monkeypatch.setattr(MockModelProvider,'complete',fail)
    a=assess(w)
    assert a.assessment_status=='ENGINEERING_ONLY'


def test_provider_qualification_separate_from_pricing(w):
    a=assess(w)
    assert w['provider'].qualification_status=='PROVIDER_QUALIFIED'
    assert w['provider'].scope=='ENGINEERING_FIXTURE_ONLY'
    assert a.assessment_status=='ENGINEERING_ONLY' and 'HOLD_MARKET_DATA_PROVIDER_LIVE' in a.hold_reasons


def test_real_forward_cannot_launder_mock(w):
    a=assess(w,pricing_mode='REAL_FORWARD')
    assert a.remaining_edge=='HOLD' and not a.formal_positive_remaining_edge


def test_report_marks_fixture_and_has_all_dimensions(w):
    a=assess(w)
    out=w['pricing'].report(vr(a),as_of=w['clock'](),pricing_mode='ENGINEERING_FIXTURE')
    assert out['声明']==['ENGINEERING_DEMO','NO_ALPHA_CLAIM','NO_INVESTMENT_ADVICE']
    assert all(k in out for k in ('市场认知','已定价','拥挤','剩余空间','反转风险','缺失维度'))

def test_narrative_heat_cannot_create_economic_pricing(w):
    from xevent.ontology.engine import OntologyEngine
    from xevent.exposures.engine import ExposureMaster
    from xevent.exposures.fixture import disclose, exposure
    from xevent.exposures.contracts import DisclosureSpec
    from xevent.graph.engine import TransmissionGraph
    from xevent.graph.fixture import request as graph_request
    w['ontology_engine']=OntologyEngine(w['ledger']); w['master']=ExposureMaster(w['ledger'])
    theme=w['ontology_engine'].theme('P8_THEME',1,event_ref=vr(w['event']),canonical_name_zh='虚构铜概念',
        description_zh='仅市场叙事',evidence_refs=list(w['event'].evidence_refs))
    d=disclose(w,2,raw_text='虚构甲公司关联虚构铜概念，仅是市场叙事')
    data={k:v for k,v in d.model_dump(mode='json').items() if k in DisclosureSpec.model_fields}
    data.update(disclosure_id='P8_NARRATIVE_DISC',disclosure_type='NARRATIVE')
    d=w['master'].disclosure(1,DisclosureSpec.model_validate(data))
    ex=w['master'].exposure(1,exposure(w,d,exposure_id='P8_NARRATIVE_EX',industry_ref=None,narrative_theme_ref=vr(theme),
        exposure_type='NARRATIVE_ASSOCIATION',validation_status='UNREVIEWED',effective_to=None))
    history=TransmissionGraph(w['ledger']).build('P8_NARRATIVE_GRAPH',1,graph_request(w,
        exposure_refs=[vr(ex)],resolution_refs=[]))
    packet=w['research'].packet('P8_NARRATIVE_PACKET',vr(history),vr(w['model']),as_of=w['clock']())
    run=w['research'].run('P8_NARRATIVE_RUN',vr(packet),MockModelProvider())
    assert run.final_choice=='NULL' and packet.narrative_path_refs
    reprice(w,stock=0.1)
    a=assess(w,analysis_ref=vr(run),path_ref=packet.narrative_path_refs[0],next_buyers=())
    assert a.remaining_edge=='HOLD' and 'ECONOMIC_PATH_HOLD' in a.hold_reasons
    assert get(w,vr(run)).final_choice=='NULL'


@pytest.mark.parametrize('buyer',[False,True])
def test_persisted_multisession_crowding(w,buyer):
    prior=[]
    for day in (0,1,2):
        start=w['start']+timedelta(days=day); end=w['end']+timedelta(days=day)
        w['clock'].value=max(w['clock'].value,end+timedelta(seconds=1))
        for label,value,stamp in (('A',100.0,start),('B',108.0,end)):
            prior.append(vr(observation(w,'TREND_'+str(day)+label,w['security'],'PRICE',value,stamp)))
    original_start=w['start']; original_end=w['end']
    w['start']+=timedelta(days=3); w['end']+=timedelta(days=3)
    w['clock'].value=w['end']+timedelta(seconds=1)
    req=request(w,stock_return=0.08,flow=5.0,prefix='MULTIDAY',buyer=buyer)
    # Same-clock baselines precede the event, not earlier post-event sessions.
    bases={}
    for kind,value in (('VOLUME',1000.0),('AMOUNT',100000.0)):
        bases[kind.lower()+'_baseline_refs']=[vr(observation(w,'PREBASE_'+kind+str(i),w['security'],kind,value,
            original_start-timedelta(days=i),original_end-timedelta(days=i))) for i in (1,2,3)]
    w['request']=req
    a=assess(w,prior_session_price_refs=prior,**bases)
    f=get(w,a.features_ref)
    assert f.traded_session_count==4 and f.volume_ratio==5.0
    assert a.recognition_state=='CONSENSUS' and a.price_in_band=='VERY_HIGH'
    assert a.crowding_band=='EXTREME' and a.remaining_edge==('THIN' if buyer else 'NONE')


@pytest.mark.parametrize('field',['timestamp_verified','unit_verified','currency_verified'])
def test_provider_cannot_qualify_without_each_dimension(w,field):
    with pytest.raises(ValueError,match='PROVIDER_QUALIFICATION'):
        revise(w,w['provider'],**{field:False})


def test_return_requires_price_endpoints(w):
    with pytest.raises(ValueError,match='RETURN_ENDPOINTS'):
        observation(w,'BAD_RETURN',w['security'],'RETURN',0.0,w['start'],w['end'],
            component_price_refs=[ref(w['request'].volume_baseline_refs[0]),ref(w['request'].volume_ref)])
