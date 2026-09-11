"""Multi-event end-to-end fixture; all upstream results use accepted public engines."""
from pathlib import Path
import pytest
from xevent.ranking.fixture import prepare_package
from xevent.ranking.contracts import RankRequest
from xevent.research.packet import vr


@pytest.fixture(scope='module')
def package_case(tmp_path_factory):
    case=prepare_package(tmp_path_factory.mktemp('p9-package')/'package.sqlite',Path(__file__).parents[1]/'configs')
    yield case
    case[0]['ledger'].close()


def get(w,r):
    return w['ledger'].get(r.object_id,r.version)


def test_actual_package_counts_and_negative_mechanisms(package_case):
    w,engine,p,empty,pricing=package_case
    m=get(w,p.manifest_ref); rank=get(w,p.rank_snapshot_ref)
    assert (m.alpha1,m.alpha2,m.beta,m.overpriced)==(2,2,1,1)
    assert m.watch>=1 and m.reject>=2 and m.total==27
    assert m.universe_total==1 and len(m.samples[0].candidate_refs)==27
    assert len(rank.economic_alpha_refs)==4 and len(rank.beta_refs)==1
    cs=[get(w,r) for r in p.candidate_refs]
    assert all(c.countercase and c.failure_conditions for c in cs if c.candidate_grade in ('ALPHA1','ALPHA2','BETA'))
    assert all(c.negative_path_refs for c in cs)
    assert len(rank.security_summaries[0].all_candidate_path_refs)==27
    assert len(rank.security_summaries[0].negative_path_refs)==9
    assert all(not a.formal_positive_remaining_edge for a in pricing)
    assert not p.formal_live_alpha and empty.empty_opportunity_list
    out=engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)
    assert out['当前状态']=='ENGINEERING_ONLY' and not out['重算原因']
    assert out['声明']==['ENGINEERING_DEMO','NO_ALPHA_CLAIM','NO_INVESTMENT_ADVICE']
    assert next(c for c in out['当前经济榜'] if c['等级']=='BETA')['排名']>4


def test_input_permutation_is_idempotent_and_world_positions_stable(package_case):
    w,engine,p,_,_=package_case
    reversed_request=p.request.model_copy(update={'history_refs':tuple(reversed(p.request.history_refs))})
    assert engine.build(p.object_id,reversed_request)==p
    a=engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)
    b=engine.report(vr(p),as_of=w['clock'](),ranking_mode=p.ranking_mode)
    assert a==b
    assert [x['排名'] for x in a['当前经济榜']]==list(range(1,len(a['当前经济榜'])+1))


def test_rank_position_change_does_not_downgrade_grade(package_case):
    w,engine,p,_,_=package_case
    history=next(r for r in p.request.history_refs if r.object_id=='P9_GRAPH_A1_B')
    first=engine.build('P9_B_ONLY',p.request.model_copy(update={'history_refs':(history,),'as_of':w['clock']()}))
    second=engine.build('P9_EXPANDED',p.request.model_copy(update={'previous_package_ref':vr(first),'as_of':w['clock']()}))
    changes=[get(w,r) for r in second.change_refs]
    moved=[c for c in changes if c.from_grade==c.to_grade=='ALPHA1']
    assert len(moved)==1 and moved[0].grade_change=='UNCHANGED' and moved[0].rank_change==1
    assert moved[0].changed_dimensions==()
