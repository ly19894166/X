"""Phase 9 additions only; accepted Phase 1–8 tests remain unchanged."""
import json
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from test_phase8_pricing import seed, w, assess, get
from xevent.ranking.contracts import *
from xevent.ranking.engine import RankingEngine
from xevent.ranking.policy import classify, ordinal_dimensions, sort_key
from xevent.research.packet import vr


def positive(**changes):
    return RankDimensions(world='ECONOMIC',exposure_type='VERIFIED_DIRECT',research_status='MOCK_PASS',pricing_status='ENGINEERING_ONLY',
        thesis_strength='HIGH',red_team_status='UNCHANGED',final_choice='TARGET',decision_source='PRIMARY',
        remaining_edge='POSITIVE',price_in_band='LOW',crowding_band='LOW',reversal_risk='LOW',
        next_buyer_status='SUPPORTED',alternative_cause_status='CURRENT_EVENT_DOMINANT',purity='HIGH',**changes)


def grade(d,**kwargs):
    return classify(d,RankRules(),countercase=['需求可能抵消供应冲击'],failures=['若披露取消则假设失效'],**kwargs)


def build(w,identity='RANK',previous=None,**changes):
    engine=RankingEngine(w['ledger'])
    try: policy=w['ledger'].get('P9_POLICY',1)
    except (ValueError,KeyError): policy=engine.policy()
    req=RankRequest(snapshot_ref=vr(w['snapshot']),history_refs=[vr(w['history'])],policy_ref=vr(policy),
        as_of=w['clock'](),previous_package_ref=vr(previous) if previous else None,**changes)
    return engine,engine.build(identity,req)


@pytest.mark.parametrize('updates,expected',[
    ({},'ALPHA1'),({'remaining_edge':'THIN'},'ALPHA2'),
    ({'price_in_band':'VERY_HIGH','remaining_edge':'NONE'},'OVERPRICED'),
    ({'final_choice':'NULL'},'REJECT'),({'research_status':'HOLD'},'WATCH'),
    ({'red_team_status':'TARGET_INVALIDATED'},'REJECT'),({'red_team_status':'NULL_PREFERRED'},'REJECT'),
    ({'world':'NARRATIVE'},'WATCH'),({'purity':'UNKNOWN'},'ALPHA2'),
    ({'systemic_basis':'BROAD_SECTOR_RELATIVE_NEUTRAL','purity':'LOW'},'BETA'),
    ({'remaining_edge':'UNKNOWN'},'WATCH'),({'thesis_strength':'LOW'},'WATCH'),
    ({'next_buyer_status':'UNKNOWN'},'WATCH'),({'crowding_band':'EXTREME'},'WATCH'),
    ({'red_team_status':'TARGET_WEAKENED'},'ALPHA2'),({'alternative_cause_status':'CAUSE_UNKNOWN'},'ALPHA2'),
])
def test_grade_rules(updates,expected):
    assert grade(positive().model_copy(update=updates))[0]==expected


def test_missing_failure_or_countercase_blocks_alpha():
    for counter,failures in (([],['条件']),(['反证'],[])):
        assert classify(positive(),RankRules(),countercase=counter,failures=failures)[:2]==('WATCH','HOLD')


def test_hard_vs_soft_missing():
    assert grade(positive(),hard=['PIT_INVALID'])[:2]==('WATCH','HOLD')
    assert grade(positive(),soft=['CROSS_ASSET_DELAYED'])[0]=='ALPHA2'
    assert grade(positive(),reject=['INVALID_PATH'])[:2]==('REJECT','REJECT')


def test_stable_tie_and_unknown_not_numeric_zero():
    rules=RankRules(); d=positive().model_copy(update={'purity':'UNKNOWN'})
    dim=ordinal_dimensions(d,rules); purity=next(x for x in dim if x.dimension=='purity')
    assert purity.ordinal is None and purity.knowledge=='SOFT_UNKNOWN'
    vectors=[SimpleNamespace(candidate_grade='ALPHA2',processing_state='VALID',dimensions=dim,tie_break=('EVENT',s,'PATH')) for s in ('B','A')]
    assert sorted(vectors,key=lambda v:sort_key(v,rules))==sorted(reversed(vectors),key=lambda v:sort_key(v,rules))
    assert sorted(vectors,key=lambda v:sort_key(v,rules))[0].tie_break[1]=='A'


@pytest.mark.parametrize('field',['holdings','cost','profit','preference','balance','position','t_plus_1_return','mfe','mae','future_success'])
def test_account_and_outcome_fields_rejected(field):
    with pytest.raises(ValidationError): RankDimensions.model_validate({**positive().model_dump(),field:1})


def test_persisted_full_sample_and_no_upstream_mutation(w):
    a=assess(w); before=w['ledger'].replay(w['clock']()); cutoff=w['clock']()
    engine,p=build(w)
    manifest=get(w,p.manifest_ref); cs=[get(w,r) for r in p.candidate_refs]
    assert manifest.universe_total==len(w['snapshot'].decisions)
    assert manifest.total==len(cs)
    assert any(c.path_ref==vr(w['path']) and c.candidate_grade=='ALPHA2' for c in cs)
    assert set(r for c in cs for r in c.negative_path_refs)==set(w['packet'].negative_path_refs)
    assert not p.formal_live_alpha
    assert engine.current(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)['freshness']=='AS_RECORDED'
    assert w['ledger'].replay(cutoff)==before
    for o in w['ledger'].history(as_of=w['clock']()):
        if type(o).__name__ in SCHEMAS:
            assert type(o).model_validate_json(o.model_dump_json())==o
            assert type(o).model_json_schema()
    assert engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)['正式Alpha'] is False


def test_empty_package_and_removed_paths_are_audited(w):
    assess(w); engine,p=build(w)
    empty=engine.build('EMPTY',p.request.model_copy(update={'history_refs':(),'as_of':w['clock'](),'previous_package_ref':vr(p)}))
    assert empty.empty_opportunity_list
    m=get(w,empty.manifest_ref)
    assert m.alpha1==m.alpha2==m.beta==0 and m.universe_total==len(w['snapshot'].decisions)
    assert m.total>=m.universe_total and m.hold>=1
    assert any(get(w,r).grade_change=='REMOVED' for r in empty.change_refs)


def test_all_reject_still_has_package_and_denominator(w):
    from xevent.registry.engine import Registry
    from xevent.registry.contracts import SecuritySpec
    engine=RankingEngine(w['ledger']); policy=engine.policy(); registry=Registry(w['ledger'])
    fields={k:v for k,v in w['security'].model_dump(mode='json').items() if k in SecuritySpec.model_fields}
    fields.update(identity_status='HOLD',identity_reason_zh='虚构身份有冲突，隔离该证券')
    registry.security(2,SecuritySpec.model_validate(fields))
    snapshot=registry.snapshot('P9_IDENTITY_HOLD',as_of=w['clock']())
    p=engine.build('ALL_REJECT',RankRequest(snapshot_ref=vr(snapshot),history_refs=[],policy_ref=vr(policy),as_of=w['clock']()))
    manifest=get(w,p.manifest_ref)
    assert p.empty_opportunity_list and manifest.total==manifest.reject==1
    c=get(w,p.candidate_refs[0])
    assert 'INVALID_IDENTITY' in c.candidate_reason_codes and c.reject_reason_refs


@pytest.mark.parametrize('field',['holdings','cost','profit','preference','account_balance','position','t_plus_1_return','mfe','mae'])
def test_research_request_has_no_account_or_label_interface(field):
    r=VersionRef(object_id='FIXED',version=1)
    with pytest.raises(ValidationError):
        RankRequest.model_validate(dict(snapshot_ref=r,history_refs=[],policy_ref=r,as_of='2025-01-01T00:00:00Z',**{field:1}))


@pytest.mark.parametrize('change',[
    {'alpha1_edges':['THIN']},{'alpha1_thesis':['LOW']},{'alpha1_risks':['EXTREME']},
    {'alpha2_buyers':['UNKNOWN']},{'dimension_order':['future_return'],'ordinal_orders':{'future_return':['SUCCESS']}}
])
def test_policy_cannot_weaken_core_gates_or_add_outcomes(change):
    with pytest.raises(ValidationError): RankRules.model_validate(change)


def test_high_return_has_no_direct_sort_dimension():
    rules=RankRules()
    thin=positive().model_copy(update={'remaining_edge':'THIN','price_in_band':'HIGH','crowding_band':'HIGH'})
    def vector(d,sid):
        g,state,_=grade(d)
        return SimpleNamespace(candidate_grade=g,processing_state=state,dimensions=ordinal_dimensions(d,rules),tie_break=('EVENT',sid,'PATH'))
    assert sort_key(vector(positive(),'LOW_RETURN'),rules)<sort_key(vector(thin,'HIGH_RETURN'),rules)
    assert not set(rules.dimension_order)&{'raw_return','price','volume','profit','future_return'}


def test_persisted_narrative_watch_is_separate_and_not_rescued(w):
    from test_phase8_pricing import test_narrative_heat_cannot_create_economic_pricing
    test_narrative_heat_cannot_create_economic_pricing(w)
    w['history']=w['ledger'].get('P8_NARRATIVE_GRAPH',1)
    engine,p=build(w,'NARRATIVE_RANK')
    r=get(w,p.rank_snapshot_ref)
    assert r.narrative_ranking and not r.economic_alpha_refs
    assert all(get(w,x).candidate_grade=='WATCH' and get(w,x).world=='NARRATIVE' for x in r.narrative_ranking)
    assert p.empty_opportunity_list
