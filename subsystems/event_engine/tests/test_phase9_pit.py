"""Ranking knowledge time, upstream freshness and execution isolation."""
from datetime import timedelta
import pytest
from pydantic import ValidationError
from test_phase8_pricing import seed,w,assess,get,new_analysis,revise
from test_phase8_review_a1 import copy_input,publish_novelty
from test_phase9_ranking import build
from xevent.ranking.contracts import *
from xevent.ranking.engine import RankingEngine
from xevent.research.packet import vr

pytestmark=pytest.mark.pit


@pytest.mark.parametrize('change,reason',[
    ('pricing','PRICING_ASSESSMENT_RECOMPUTE_REQUIRED'),('analysis','ANALYSIS_RECOMPUTE_REQUIRED'),
    ('policy','RANK_POLICY_RECOMPUTE_REQUIRED'),('market','MARKET_OBSERVATION_RECOMPUTE_REQUIRED'),
    ('novelty','NOVELTY_RECOMPUTE_REQUIRED'),('context','PRICINGCONTEXT_RECOMPUTE_REQUIRED'),
    ('snapshot','SNAPSHOT_RECOMPUTE_REQUIRED')])
def test_new_knowledge_changes_current_not_old_cutoff(w,change,reason):
    assess(w); engine,p=build(w); cutoff=w['clock'](); replay=w['ledger'].replay(cutoff)
    if change=='pricing': assess(w,'DIFFERENT_PRICING_ID')
    elif change=='analysis': new_analysis(w)
    elif change=='policy': engine.policy('DIFFERENT_POLICY_ID')
    elif change=='market': copy_input(w,get(w,w['request'].price_refs[-1]),'DIFFERENT_PRICE_ID')
    elif change=='novelty': publish_novelty(w,'R1','P9_NEW_NOVELTY')
    elif change=='context': copy_input(w,w['context'],'DIFFERENT_CONTEXT_ID')
    elif change=='snapshot': engine.registry.snapshot('DIFFERENT_UNIVERSE_ID',as_of=w['clock']())
    now=engine.current(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)
    assert reason in now['recompute_reasons'] and 'RANK_RECOMPUTE_REQUIRED' in now['recompute_reasons']
    assert now['current_status']=='HOLD'
    assert engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)['当前经济榜']==[]
    assert engine.current(vr(p),as_of=cutoff,ranking_mode=p.ranking_mode)['freshness']=='AS_RECORDED'
    assert w['ledger'].replay(cutoff)==replay==w['ledger'].replay(cutoff)


def test_new_policy_cannot_be_explicitly_bypassed_at_build(w):
    assess(w); engine,p=build(w); engine.policy('NEW_SCOPE_SAME_POLICY')
    _,new=build(w,'NEW_PACKAGE')
    assert 'RANK_POLICY_RECOMPUTE_REQUIRED' in new.hold_reasons
    assert all(get(w,r).candidate_grade not in ('ALPHA1','ALPHA2','BETA') for r in new.candidate_refs)
    assert p.request.policy_ref.object_id=='P9_POLICY'


def test_historical_market_and_policy_do_not_refresh_forward(w):
    assess(w); engine,p=build(w)
    copy_input(w,get(w,w['request'].price_refs[-1]),'HIST_PRICE',mode='HISTORICAL_REPLAY')
    engine.policy('HIST_RANK_POLICY',ranking_mode='HISTORICAL_REPLAY')
    assert engine.current(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)['freshness']=='AS_RECORDED'
    with pytest.raises(ValueError,match='MODE'): engine.current(vr(p),as_of=w['clock'](),ranking_mode='HISTORICAL_REPLAY')


def test_delayed_publication_invisible_before_completion(w):
    assess(w); engine=RankingEngine(w['ledger']); policy=engine.policy(); cutoff=w['clock']()
    req=RankRequest(snapshot_ref=vr(w['snapshot']),history_refs=[vr(w['history'])],policy_ref=vr(policy),as_of=cutoff)
    def delay(stage):
        if stage=='after_rank_package': w['clock'].value+=timedelta(minutes=2)
    w['ledger'].fault=delay
    p=engine.build('DELAYED',req)
    assert p.available_at>cutoff+timedelta(minutes=1)
    assert not any(o.object_id==p.object_id for o in w['ledger'].history(as_of=cutoff+timedelta(minutes=1)))


def test_future_input_rejected(w):
    cutoff=w['clock'](); a=assess(w); engine=RankingEngine(w['ledger']); policy=engine.policy()
    req=RankRequest(snapshot_ref=vr(w['snapshot']),history_refs=[vr(w['history'])],policy_ref=vr(policy),as_of=cutoff)
    with pytest.raises(ValueError): engine.build('FUTURE_INPUT',req)
    assert not w['ledger'].history(kind='OpportunityPackage',as_of=w['clock']())


def test_display_eligibility_and_later_account_policy_do_not_change_research(w):
    assess(w); engine,p=build(w); original=engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)
    policy=engine.display_policy('ACCOUNT',allowed_boards=['SZ_MAIN','CHINEXT','STAR'])
    yes=engine.execution('DISPLAY',vr(w['security']),vr(policy),as_of=w['clock']())
    cutoff=w['clock']()
    no_policy=engine.display_policy('ACCOUNT',allowed_boards=[],version=2)
    no=engine.execution('DISPLAY',vr(w['security']),vr(no_policy),as_of=w['clock'](),version=2)
    assert yes.eligibility=='ELIGIBLE' and no.eligibility=='INELIGIBLE'
    assert engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)==original
    shown=engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode,execution_refs=[vr(no)])
    assert shown['当前经济榜'][0]['执行资格']=='INELIGIBLE'
    assert shown['当前经济榜'][0]['排名']==original['当前经济榜'][0]['排名']
    assert shown['当前经济榜'][0]['等级']==original['当前经济榜'][0]['等级']
    assert w['ledger'].get('DISPLAY',1)==yes and not any(o.object_id=='DISPLAY' and o.version==2 for o in w['ledger'].history(as_of=cutoff))


def test_real_forward_is_hold_and_not_visible_as_live(w):
    assess(w); engine=RankingEngine(w['ledger']); policy=engine.policy(ranking_mode='REAL_FORWARD')
    req=RankRequest(snapshot_ref=vr(w['snapshot']),history_refs=[vr(w['history'])],policy_ref=vr(policy),as_of=w['clock'](),ranking_mode='REAL_FORWARD')
    p=engine.build('REAL_REQUEST',req)
    assert 'HOLD_REAL_FORWARD_QUALIFICATION' in p.hold_reasons
    assert p.empty_opportunity_list and not p.formal_live_alpha
    from xevent.contracts.common import PITQuery
    assert not p.is_visible(PITQuery(as_of=w['clock'](),mode='LIVE_FORWARD'))


def test_grade_change_separate_from_rank_and_atomic_recovery(w):
    assess(w); engine,p=build(w)
    _,second=build(w,'NEXT_PACKAGE',previous=p)
    changes=[get(w,r) for r in second.change_refs]
    assert all(c.grade_change=='UNCHANGED' for c in changes)
    assert all(c.rank_change in (0,None) for c in changes)
    before=w['ledger'].replay(w['clock']())
    def fail(stage):
        if stage=='after_rank_package': raise RuntimeError('fixture crash')
    w['ledger'].fault=fail
    with pytest.raises(RuntimeError): build(w,'CRASH')
    assert w['ledger'].replay(w['clock']())==before


def test_new_mapping_under_different_id_requires_recomputation(w):
    from xevent.graph.engine import TransmissionGraph
    from xevent.graph.fixture import request
    assess(w); engine,p=build(w); cutoff=w['clock']()
    h=TransmissionGraph(w['ledger']).build('P9_NEW_MAPPING',1,request(w))
    state=engine.current(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)
    assert 'MAPPING_RECOMPUTE_REQUIRED' in state['recompute_reasons']
    assert engine.current(vr(p),as_of=cutoff,ranking_mode=p.ranking_mode)['freshness']=='AS_RECORDED'


def test_later_metric_same_semantic_scope_invalidates_purity(w):
    from xevent.exposures.engine import ExposureMaster
    from xevent.exposures.fixture import metric
    assess(w); engine,p=build(w); cutoff=w['clock']()
    ExposureMaster(w['ledger']).metric(1,metric(w['ex'],metric_id='P9_REVIEWED_METRIC_NEW_ID'))
    assert 'METRIC_RECOMPUTE_REQUIRED' in engine.current(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)['recompute_reasons']
    assert engine.current(vr(p),as_of=cutoff,ranking_mode=p.ranking_mode)['freshness']=='AS_RECORDED'


def test_historical_package_remains_historical_and_forward_updates_are_isolated(w):
    from xevent.contracts.common import PITQuery
    assess(w)
    engine=RankingEngine(w['ledger'])
    policy=engine.policy('HISTORY_POLICY',ranking_mode='HISTORICAL_REPLAY')
    req=RankRequest(snapshot_ref=vr(w['snapshot']),history_refs=[vr(w['history'])],policy_ref=vr(policy),
        as_of=w['clock'](),ranking_mode='HISTORICAL_REPLAY')
    p=engine.build('HISTORICAL_PACKAGE',req)
    assert p.ranking_mode=='HISTORICAL_REPLAY' and not p.formal_live_alpha
    assert not p.is_visible(PITQuery(as_of=w['clock'](),mode='LIVE_FORWARD'))
    assess(w,'LATER_FORWARD_PRICING')
    engine.policy('LATER_FORWARD_POLICY')
    assert engine.current(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)['freshness']=='AS_RECORDED'
    with pytest.raises(ValueError,match='MODE'):
        engine.current(vr(p),as_of=w['clock'](),ranking_mode='MOCK_FORWARD')


def test_append_only_package_revision_records_grade_downgrade(w):
    assess(w); engine,p=build(w); cutoff=w['clock']()
    revise(w,w['context'])
    assess(w,'STALE_CONTEXT_ASSESSMENT')
    req=p.request.model_copy(update={'as_of':w['clock'](),'previous_package_ref':vr(p)})
    second=engine.build(p.object_id,req,version=2)
    changes=[get(w,r) for r in second.change_refs]
    downgrade=next(c for c in changes if c.from_grade=='ALPHA2')
    assert downgrade.to_grade=='WATCH' and downgrade.grade_change=='DOWNGRADED'
    assert 'pricing_status' in downgrade.changed_dimensions
    assert downgrade.change_reason_codes and downgrade.rank_change is None
    assert w['ledger'].get(p.object_id,1)==p
    assert not any(o.object_id==p.object_id and o.version==2 for o in w['ledger'].history(as_of=cutoff))
