"""Phase 9 Review A1 additions; accepted tests remain unchanged."""
import pytest
from pydantic import ValidationError
from test_phase8_pricing import seed, w, assess, get
from test_phase9_ranking import positive, grade, build
from xevent.ranking.contracts import RankRules, RankRequest, BETA_CORE, GRADE_ORDER
from xevent.ranking.policy import grade_change
from xevent.research.packet import vr
from xevent.graph.engine import TransmissionGraph
from xevent.graph.fixture import request as graph_request
from xevent.exposures.engine import ExposureMaster
from xevent.exposures.fixture import metric, disclose, exposure


@pytest.mark.parametrize('dimension',BETA_CORE)
def test_beta_core_unknown_never_valid(dimension):
    d=positive().model_copy(update={'systemic_basis':'BROAD_SECTOR_RELATIVE_NEUTRAL','purity':'LOW',dimension:'UNKNOWN'})
    result=grade(d)
    assert result[:2]!=('BETA','VALID') and 'BLOCKING_UNKNOWN:'+dimension in result[2]


def test_beta_known_core_and_explicit_buyer_exception():
    d=positive().model_copy(update={'systemic_basis':'BROAD_SECTOR_RELATIVE_NEUTRAL','purity':'LOW','next_buyer_status':'UNKNOWN'})
    assert grade(d)[:2]==('BETA','VALID')
    assert RankRules().beta_unknown_policy=='CORE_KNOWN_COMPANY_BUYER_OPTIONAL'


@pytest.mark.parametrize('order',[
    ('BETA','ALPHA1','ALPHA2','WATCH','OVERPRICED','REJECT'),tuple(reversed(GRADE_ORDER))])
def test_v01_grade_order_cannot_be_reordered(order):
    with pytest.raises(ValidationError,match='RANK_GRADE_ORDER'): RankRules(grade_order=order)


@pytest.mark.parametrize('before,after,expected',[
    ('ALPHA2','ALPHA1','UPGRADED'),('ALPHA1','ALPHA2','DOWNGRADED'),('ALPHA1','ALPHA1','UNCHANGED')])
def test_shared_grade_semantics(before,after,expected):
    assert grade_change(before,after)==expected


@pytest.mark.pit
def test_history_versions_fail_closed_in_both_orders(w):
    assess(w); engine,p=build(w)
    newer=TransmissionGraph(w['ledger']).build(w['history'].object_id,2,graph_request(w))
    for rs in ((vr(w['history']),vr(newer)),(vr(newer),vr(w['history']))):
        with pytest.raises(ValidationError,match='RANK_HISTORY_VERSION_AMBIGUITY'):
            RankRequest.model_validate({**p.request.model_dump(),'history_refs':rs,'as_of':w['clock']()})
        with pytest.raises(ValueError,match='RANK_HISTORY_VERSION_AMBIGUITY'):
            engine.build('A1_AMBIGUOUS_VERSIONS',p.request.model_copy(update={'history_refs':rs,'as_of':w['clock']()}))
    old=engine.build('A1_OLD_HISTORY',p.request.model_copy(update={'as_of':w['clock']()}))
    assert 'MAPPING_RECOMPUTE_REQUIRED' in get(w,old.candidate_refs[0]).candidate_reason_codes
    current=engine.build('A1_NEW_HISTORY',p.request.model_copy(update={'history_refs':(vr(newer),),'as_of':w['clock']()}))
    assert current.request.history_refs==(vr(newer),)
    assert all('MAPPING_RECOMPUTE_REQUIRED' not in get(w,r).candidate_reason_codes for r in current.candidate_refs)


@pytest.mark.pit
def test_first_revenue_metric_and_conflicting_scopes_recompute(w):
    from xevent.research.provider import MockModelProvider
    w['master']=ExposureMaster(w['ledger'])
    w['seed']=w['seed'].model_copy(update={'event_id':'A1_DISCLOSURE_EVENT'})
    disclosure=disclose(w,2,raw_text='虚构甲更正年报：铜矿收入72，总收入100，产量20；人工核验收入')
    w['ex']=w['master'].exposure(2,exposure(w,disclosure,effective_to=None))
    w['history']=TransmissionGraph(w['ledger']).build('A1_METRIC_GRAPH',1,graph_request(w))
    packet=w['research'].packet('A1_PACKET',vr(w['history']),vr(w['model']),as_of=w['clock']())
    w['research'].run('A1_RESEARCH',vr(packet),MockModelProvider())
    engine,p=build(w,'A1_NO_METRIC'); cutoff=w['clock']()
    cs=[get(w,r) for r in p.candidate_refs]
    c=next(c for c in cs if c.path_ref and get(w,c.path_ref).exposure_ref==vr(w['ex']))
    assert c.purity=='UNKNOWN' and not c.metric_refs
    first=w['master'].metric(1,metric(w['ex'],metric_id='A1_FIRST_REVENUE',numerator=72.0))
    state=engine.current(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)
    assert state['current_status']=='HOLD'
    assert {'METRIC_RECOMPUTE_REQUIRED','RANK_RECOMPUTE_REQUIRED'}<=set(state['recompute_reasons'])
    assert engine.current(vr(p),as_of=cutoff,ranking_mode=p.ranking_mode)['freshness']=='AS_RECORDED'
    rebuilt=engine.build('A1_WITH_METRIC',p.request.model_copy(update={'as_of':w['clock']()}))
    c2=next(get(w,r) for r in rebuilt.candidate_refs if get(w,r).path_ref==c.path_ref)
    assert c2.purity=='HIGH' and vr(first) in c2.metric_refs
    cutoff2=w['clock']()
    w['master'].metric(1,metric(w['ex'],metric_id='A1_CONFLICTING_SCOPE',numerator=72.0,scope='独立口径'))
    assert 'METRIC_RECOMPUTE_REQUIRED' in engine.current(vr(rebuilt),as_of=w['clock'](),ranking_mode=p.ranking_mode)['recompute_reasons']
    assert engine.current(vr(rebuilt),as_of=cutoff2,ranking_mode=p.ranking_mode)['freshness']=='AS_RECORDED'
    multiple=engine.build('A1_MULTI_METRIC',p.request.model_copy(update={'as_of':w['clock']()}))
    c3=next(get(w,r) for r in multiple.candidate_refs if get(w,r).path_ref==c.path_ref)
    assert c3.purity=='UNKNOWN' and len(c3.metric_refs)==2
    w['master'].metric(2,metric(w['ex'],metric_id='A1_FIRST_REVENUE',numerator=72.0))
    assert 'METRIC_RECOMPUTE_REQUIRED' in engine.current(vr(multiple),as_of=w['clock'](),ranking_mode=p.ranking_mode)['recompute_reasons']

@pytest.mark.pit
def test_different_history_ids_same_mechanism_rejected_independent_of_order(w):
    assess(w); engine,p=build(w)
    other=TransmissionGraph(w['ledger']).build('A1_OTHER_HISTORY',1,graph_request(w))
    for rs in ((vr(w['history']),vr(other)),(vr(other),vr(w['history']))):
        req=p.request.model_copy(update={'history_refs':rs,'as_of':w['clock']()})
        with pytest.raises(ValueError,match='RANK_AMBIGUOUS_SCOPE'): engine.build('A1_AMBIGUOUS',req)
    assert not any(o.object_id=='A1_AMBIGUOUS' for o in w['ledger'].history(as_of=w['clock']()))


def test_persisted_beta_contract_rejects_unknown_core(w):
    from xevent.ranking.contracts import CandidateVersion
    assess(w); engine,p=build(w)
    original=next(get(w,r) for r in p.candidate_refs if get(w,r).countercase)
    data={**original.model_dump(),**positive().model_dump(),'candidate_grade':'BETA','processing_state':'VALID',
        'systemic_basis':'BROAD_SECTOR_RELATIVE_NEUTRAL','purity':'LOW'}
    assert CandidateVersion.model_validate(data).candidate_grade=='BETA'
    for name in BETA_CORE:
        with pytest.raises(ValidationError,match='RANK_BETA_BLOCKING_UNKNOWN'):
            CandidateVersion.model_validate({**data,name:'UNKNOWN'})


def test_grade_unchanged_when_rank_moves_one_to_three(w):
    from xevent.ranking.contracts import CandidateChange
    assess(w); engine,p=build(w)
    original=get(w,p.change_refs[0])
    moved=CandidateChange.model_validate({**original.model_dump(),
        'previous_candidate_ref':p.candidate_refs[0],'current_candidate_ref':p.candidate_refs[0],
        'from_grade':'ALPHA1','to_grade':'ALPHA1','grade_change':grade_change('ALPHA1','ALPHA1'),
        'previous_rank':1,'current_rank':3,'rank_change':2,'changed_dimensions':[]})
    assert moved.grade_change=='UNCHANGED' and moved.rank_change==2


def test_two_companies_three_securities_preserve_paths_and_display_isolation(w):
    from xevent.registry.engine import Registry
    from xevent.registry.contracts import CompanySpec
    from xevent.exposures.fixture import add_security
    from xevent.ranking.policy import sort_key
    w['registry']=Registry(w['ledger'])
    fields={k:v for k,v in w['company'].model_dump().items() if k in CompanySpec.model_fields}
    fields.update(company_id='A1_CO_B',canonical_name_zh='虚构乙公司',legal_name='虚构乙有限公司',company_identifier='A1-LEGAL-B')
    company_b=w['registry'].company(1,CompanySpec.model_validate(fields))
    second=add_security(w,'A1_SEC_A2',security_code='000002',ticker='000002.SZ')
    third=add_security({**w,'company':company_b},'A1_SEC_B',security_code='000003',ticker='000003.SZ')
    w['snapshot']=w['registry'].snapshot('A1_MULTI_UNIVERSE',as_of=w['clock']())
    w['history']=TransmissionGraph(w['ledger']).build('A1_MULTI_GRAPH',1,graph_request(w))
    engine,p=build(w,'A1_MULTI_PACKAGE')
    manifest=get(w,p.manifest_ref); snapshot=get(w,p.rank_snapshot_ref)
    candidates=[get(w,r) for r in p.candidate_refs]
    assert manifest.universe_total==3 and len({c.company_ref for c in candidates})==2
    assert len({c.security_ref for c in candidates})==3
    assert sum(c.path_ref is not None for c in candidates)>=2
    assert len(snapshot.security_summaries)==3
    vectors=[get(w,c.rank_vector_ref) for c in candidates]
    rules=get(w,p.request.policy_ref).rules
    assert sorted(vectors,key=lambda x:sort_key(x,rules))==sorted(reversed(vectors),key=lambda x:sort_key(x,rules))
    # No fabricated per-security research/pricing: missing branches remain HOLD/empty economic rank.
    assert not snapshot.economic_alpha_refs and p.empty_opportunity_list
    yes=engine.display_policy('A1_MULTI_YES',allowed_boards=['SZ_MAIN'])
    no=engine.display_policy('A1_MULTI_NO',allowed_boards=[])
    before=engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)
    refs=[]
    for i,sec in enumerate((w['security'],second,third)):
        allowed=engine.execution('A1_ALLOWED_'+str(i),vr(sec),vr(yes),as_of=w['clock']())
        denied=engine.execution('A1_DENIED_'+str(i),vr(sec),vr(no),as_of=w['clock']())
        assert allowed.eligibility=='ELIGIBLE' and denied.eligibility=='INELIGIBLE'
        refs.append(vr(denied))
    after=engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode,execution_refs=tuple(reversed(refs)))
    assert before['当前经济榜']==after['当前经济榜']
    assert get(w,p.rank_snapshot_ref)==snapshot
