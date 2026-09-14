"""New Phase10 invariants. Original Phase1-9 tests are not edited."""
import ast
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from xevent.evaluation.contracts import *
from xevent.evaluation.calendar import add_minutes, next_session, windows
from xevent.evaluation.engine import EvaluationEngine, vr, raw, group_members
from xevent.evaluation.store import LabelLedger
from xevent.evaluation.report import report, summarize, interval
from xevent.evaluation.fixture import prepare, quote, finish
from xevent.exposures.fixture import FixtureClock


def time(s): return datetime.fromisoformat(s.replace('Z','+00:00'))


def calendar():
    days=[]; closed=[]
    start=time('2026-09-11T00:00:00+08:00')
    for i in range(12):
        d=start+timedelta(days=i)
        if d.weekday()>=5 or i==3: closed.append(str(d.date())); continue
        days.append(SessionDay(trading_date=str(d.date()),intervals=((d+timedelta(hours=9,minutes=30),d+timedelta(hours=11,minutes=30)),
            (d+timedelta(hours=13),d+timedelta(hours=15)))))
    session=SimpleNamespace(utc_offset_minutes=480)
    return SimpleNamespace(days=days,closed_dates=closed,session=session,coverage_start=start.astimezone(timezone.utc),
        coverage_end=(start+timedelta(days=12)).astimezone(timezone.utc),qualification_status='ENGINEERING_QUALIFIED')


@pytest.mark.pit
@pytest.mark.parametrize('start,minutes,expected',[
    ('2026-09-11T11:20:00+08:00',30,'2026-09-11T13:20:00+08:00'),
    ('2026-09-11T14:45:00+08:00',30,'2026-09-15T09:45:00+08:00'),
    ('2026-09-11T14:30:00+08:00',30,'2026-09-11T15:00:00+08:00'),
    ('2026-09-11T15:01:00+08:00',30,'2026-09-15T10:00:00+08:00'),
    ('2026-09-12T11:00:00+08:00',30,'2026-09-15T10:00:00+08:00'),
])
def test_trading_minutes(start,minutes,expected):
    assert add_minutes(calendar(),time(start),minutes)==time(expected)


@pytest.mark.pit
def test_six_windows_and_holidays():
    ws=windows(calendar(),time('2026-09-11T14:30:00+08:00'))
    assert tuple(w.name for w in ws)==WINDOWS
    assert ws[2].end==time('2026-09-15T09:35:00+08:00')
    assert ws[3].end==time('2026-09-15T10:00:00+08:00')
    assert ws[4].end==time('2026-09-15T15:00:00+08:00')
    assert ws[5].end==time('2026-09-17T15:00:00+08:00')


def test_calendar_missing_dates_fail_closed():
    cal=calendar(); cal.closed_dates=[]
    with pytest.raises(ValueError,match='CALENDAR_UNKNOWN'): next_session(cal,time('2026-09-11T14:00:00+08:00'))


@pytest.mark.parametrize('change',[{'windows':['T1_1000']},{'commission':-0.1},{'slippage':-0.2},{'t_plus_one':False},
    {'interval_method':'CHOOSE_BEST'},{'entry_policy':'DAILY_LOW'},{'exit_policy':'DAILY_HIGH'},{'future_return':0.1}])
def test_plan_cannot_select_best_window_or_future_features(change):
    with pytest.raises(ValidationError): EvaluationRules.model_validate(change)


@pytest.mark.parametrize('field,value',[('entry_status','LIMIT_BLOCKED'),('exit_status','SUSPENDED'),('t_plus_one_satisfied',False),
    ('settlement_kind','OBSERVATIONAL_OUTCOME')])
def test_simulated_return_requires_executability(field,value):
    data=dict(entry_status='EXECUTABLE',exit_status='EXECUTABLE',settlement_kind='REALIZABLE_SETTLEMENT',t_plus_one_satisfied=True,
        simulated_return=0.1,cost_plan_ref=dict(object_id='PLAN',version=1),reason_codes=[])
    data[field]=value
    with pytest.raises(ValidationError,match='NOT_REALIZABLE'): ExecutionSimulation.model_validate(data)


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    root=tmp_path_factory.mktemp('phase10')
    w=prepare(root/'features.sqlite',root/'labels.sqlite',Path('configs'))
    yield w
    w['ledger'].close(); w['labels'].close()


@pytest.fixture
def world(prepared,tmp_path):
    target=tmp_path/'labels.sqlite'
    with sqlite3.connect(prepared['labels'].path) as source, sqlite3.connect(target) as out: source.backup(out)
    clock=FixtureClock(prepared['clock'].value.isoformat())
    labels=LabelLedger(target,feature_path=prepared['ledger'].path,clock=clock)
    w={**prepared,'labels':labels,'evaluation':EvaluationEngine(labels),'clock':clock}
    yield w
    labels.close()


def settle_all(w):
    return finish(w)


@pytest.mark.pit
def test_physical_feature_label_isolation(world):
    with pytest.raises(ValueError,match='ISOLATION'): LabelLedger(world['ledger'].path,feature_path=world['ledger'].path)
    before={ (o.object_id,o.version):o.content_hash for o in world['ledger'].history(as_of=world['clock']()) }
    r=settle_all(world)
    after={ (o.object_id,o.version):o.content_hash for o in world['ledger'].history(as_of=world['clock']()) }
    assert before==after
    assert world['labels'].get(world['run'].object_id,1).manifest_hash==world['run'].manifest_hash
    assert r.health.candidate_total==world['run'].candidate_total+world['empty_run'].candidate_total
    assert r.health.empty_list_rate==0.5
    assert any(s.group=='REJECT' and s.total_frozen for s in r.statistics)
    assert all('NO_ALPHA_CLAIM' in r.notices for _ in [0])


@pytest.mark.pit
def test_outcome_not_visible_before_endpoint_and_commit(world):
    r=settle_all(world)
    outcomes=[world['labels'].get(x.object_id,x.version) for x in r.outcome_refs]
    for o in outcomes:
        assert o.available_at>=o.window.end
        assert o not in world['labels'].history(as_of=o.window.end-timedelta(seconds=1),kind='Outcome')
        assert all(i.available_at<=o.available_at for i in o.input_version_refs)


@pytest.mark.pit
def test_unfinished_window_no_future_outcome(world):
    run=world['run']; before=world['clock']()
    assert world['evaluation'].settle(vr(run),as_of=before)==[]
    qs=world['labels'].history(as_of=world['clock'](),kind='SampleQuality')
    assert len(qs)==run.candidate_total*6
    assert all('WINDOW_NOT_FINISHED' in q.quality_reasons for q in qs)


def test_missing_quotes_keep_all_samples(world):
    ws=windows(world['calendar'],world['run'].package_available_at)
    world['clock'].value=ws[-1].end+timedelta(minutes=2)
    for r in (world['run'],world['empty_run']): world['evaluation'].settle(vr(r),as_of=world['clock']())
    r=report(world['evaluation'],'MISSING_REPORT',(vr(world['run']),vr(world['empty_run'])),as_of=world['clock']())
    all_rows=[s for s in r.statistics if s.group=='ALL_FROZEN']
    assert all(s.data_hold==s.total_frozen and s.sample_n==0 for s in all_rows)
    assert 'FORWARD_HOLD_INSUFFICIENT_SAMPLE' in r.hold_reasons


@pytest.mark.parametrize('blocked,limit',[('LIMIT_BLOCKED','ONE_PRICE_LIMIT'),('LIMIT_BLOCKED','OPEN_LIMIT'),
    ('LIMIT_BLOCKED','DOWN_LIMIT'),('SUSPENDED','NONE'),('NO_LIQUIDITY','NONE'),('UNKNOWN_EXECUTABILITY','TOUCHED_LIMIT')])
def test_execution_blocks_not_assumed_filled(world,blocked,limit):
    w=world; run=w['run']; ws=windows(w['calendar'],run.package_available_at)
    entry=next_session(w['calendar'],run.package_available_at+timedelta(seconds=60))
    quote(w,'BLOCK_ENTRY',entry,100.0,entry=blocked,exit=blocked,limit=limit)
    quote(w,'BLOCK_EXIT',ws[-1].end,105.0,entry=blocked,exit=blocked,limit=limit)
    out=w['evaluation'].settle(vr(run),as_of=w['clock']())
    final=[o for o in out if o.window.name=='T3_CLOSE']
    assert final and all(o.simulation.simulated_return is None for o in final)
    assert any(o.reference_return is not None for o in final)
    assert len(out)==run.candidate_total*6


def test_costs_t1_and_mfe_not_substituted(world):
    r=settle_all(world)
    out=[world['labels'].get(x.object_id,x.version) for x in r.outcome_refs]
    refs=[o for o in out if o.reference_return is not None]
    assert refs
    assert all(o.simulation.simulated_return is None for o in refs if o.window.name in ('H30','T_CLOSE'))
    assert any(o.simulation.simulated_return is not None and o.simulation.simulated_return<o.reference_return for o in refs)
    assert all(o.mfe is None and o.diagnostic_reason=='DIAGNOSTIC_GRID_INCOMPLETE' for o in refs)


@pytest.mark.pit
def test_prepackage_price_cannot_be_entry(world):
    w=world; run=w['run']; ws=windows(w['calendar'],run.package_available_at)
    quote(w,'BEFORE_PACKAGE',run.package_available_at-timedelta(minutes=1),100.0)
    quote(w,'AFTER',ws[-1].end,110.0)
    out=w['evaluation'].settle(vr(run),as_of=w['clock']())
    assert all(o.entry_quote_ref is None and o.reference_return is None for o in out)


def test_report_cannot_drop_registered_run(world):
    settle_all(world)
    with pytest.raises(ValueError,match='REPORT_RUN_OMISSION'):
        report(world['evaluation'],'DROP',(vr(world['run']),),as_of=world['clock']())


@pytest.mark.pit
def test_settle_idempotency_and_revisions(world):
    w=world; finish(w); run=w['run']
    prior=w['labels'].history(as_of=w['clock'](),kind='Outcome')
    at=next(o.as_of for o in prior if o.research_run_ref==vr(run))
    w['evaluation'].settle(vr(run),as_of=at)
    assert w['labels'].history(as_of=w['clock'](),kind='Outcome')==prior
    with pytest.raises(ValueError,match='REVISION_REASON'): w['evaluation'].settle(vr(run),as_of=w['clock'](),version=2)
    w['evaluation'].settle(vr(run),as_of=w['clock'](),version=2,revision_reason='显式修订重新核验，旧结果保留')
    assert all(w['labels'].get(o.object_id,o.version)==o for o in prior)


def test_no_upstream_label_imports():
    root=Path('src/xevent')
    for module in ('ranking','pricing','research','graph','states','ontology','exposures','registry'):
        for path in (root/module).glob('*.py'):
            tree=ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom): assert 'evaluation' not in (node.module or ''), str(path)
                if isinstance(node,ast.Import): assert all('evaluation' not in a.name for a in node.names),str(path)


def statistic_samples(values,clusters=None):
    run=SimpleNamespace(object_id='run')
    result=[]
    for i,v in enumerate(values):
        c=SimpleNamespace(security_ref=SimpleNamespace(object_id='SEC'+str(i)))
        q=SimpleNamespace(quality='QUALIFIED',reference_eligible=True,simulated_eligible=True)
        o=SimpleNamespace(reference_return=v,simulation=SimpleNamespace(simulated_return=v-0.001),mfe=None,mae=None)
        result.append((run,c,clusters[i] if clusters else 'EVENT'+str(i),o,q))
    return result


def test_ten_securities_one_event_is_one_cluster():
    s=summarize('ALPHA1','T1_CLOSE',statistic_samples([0.1]*10,['ONE']*10),EvaluationRules())
    assert s.sample_n==10 and s.event_cluster_n==1
    assert s.interval is None and s.conclusion=='INSUFFICIENT_SAMPLE'


def test_negative_results_are_legal_and_interval_deterministic():
    rules=EvaluationRules(min_candidates=2,min_clusters=2)
    samples=statistic_samples([-0.02,-0.03,-0.04])
    a=summarize('ALPHA1','T1_CLOSE',samples,rules)
    b=summarize('ALPHA1','T1_CLOSE',list(reversed(samples)),rules)
    assert a==b and a.conclusion=='NEGATIVE_EDGE'
    assert a.interval[1]<0


def test_pit_violation_forces_forward_health_hold():
    data=dict(runs_expected=1,runs_created=1,runs_settled=1,runs_late=0,candidate_total=1,outcome_total=1,
        quote_coverage=1.0,calendar_coverage=1.0,settlement_coverage=1.0,stale_data_count=0,missing_data_count=0,
        execution_hold_count=0,empty_list_rate=0.0,pit_violation_count=1,health='ENGINEERING_ONLY')
    with pytest.raises(ValidationError,match='FORWARD_PIT_HOLD'): ForwardHealth.model_validate(data)


@pytest.mark.pit
def test_plan_version_never_rewrites_registered_run(world):
    w=world; old=w['evaluation_plan']; frozen=w['run']
    new=w['evaluation'].plan(old.object_id,calendar_ref=old.calendar_ref,rank_policy_ref=old.rank_policy_ref,epoch='EPOCH_2',
        registration_start=(w['clock']()+timedelta(days=1)).isoformat(),registration_end=(w['clock']()+timedelta(days=2)).isoformat(),
        version=2,revision_reason='未来独立政策期；不回填旧run',rules={'commission':0.002})
    assert new.rules.commission!=old.rules.commission
    assert w['labels'].get(frozen.object_id,1)==frozen
    assert frozen.evaluation_plan_ref==vr(old)


@pytest.mark.pit
@pytest.mark.parametrize('mode',['PUBLIC_PIT_RESEARCH','HISTORICAL_REPLAY','MOCK_FORWARD','REAL_FORWARD'])
def test_fixture_cannot_masquerade_as_other_run_mode(world,mode):
    w=world; old=w['evaluation_plan']; start=w['clock']()+timedelta(seconds=1)
    plan=w['evaluation'].plan('OTHER_MODE',calendar_ref=old.calendar_ref,rank_policy_ref=old.rank_policy_ref,epoch='OTHER',
        registration_start=start.isoformat(),registration_end=(start+timedelta(days=1)).isoformat(),evaluation_mode=mode)
    w['clock'].value=start+timedelta(seconds=1)
    with pytest.raises(ValueError,match='MODE_ISOLATION|HOLD_REAL_FORWARD'):
        w['evaluation'].register('FALSE_FORWARD',features=w['ledger'],package_ref=vr(w['package']),plan_ref=vr(plan))


@pytest.mark.pit
def test_late_registration_cannot_use_known_outcomes(world):
    w=world
    w['clock'].value=windows(w['calendar'],w['run'].package_available_at)[0].end+timedelta(seconds=1)
    with pytest.raises(ValueError,match='REGISTRATION'):
        w['evaluation'].register('LATE',features=w['ledger'],package_ref=vr(w['package']),plan_ref=vr(w['evaluation_plan']))


@pytest.mark.pit
def test_atomic_settlement_crash_before_commit(world):
    w=world; ws=windows(w['calendar'],w['run'].package_available_at)
    w['clock'].value=ws[-1].end+timedelta(minutes=1)
    def fault(stage):
        if stage=='before_commit': raise RuntimeError('simulated crash')
    w['labels'].fault=fault
    with pytest.raises(RuntimeError): w['evaluation'].settle(vr(w['run']),as_of=w['clock']())
    assert w['labels'].history(as_of=w['clock'](),kind='Outcome')==[]
    assert w['labels'].history(as_of=w['clock'](),kind='SampleQuality')==[]
    w['labels'].fault=lambda stage:None


def test_complete_grid_mfe_is_not_reference_return(world):
    w=world; run=w['run']; window=windows(w['calendar'],run.package_available_at)[0]
    start=next_session(w['calendar'],run.package_available_at+timedelta(seconds=60))
    t=start; i=0
    while t<=window.end:
        value=100.0 if i==0 else 98.0 if t==window.end else 105.0
        quote(w,'GRID'+str(i),t,value)
        i+=1; t+=timedelta(minutes=1)
    out=w['evaluation'].settle(vr(run),as_of=w['clock']())
    known=[o for o in out if o.reference_return is not None]
    assert known and known[0].mfe==pytest.approx(0.05)
    assert known[0].reference_return==pytest.approx(-0.02)
    assert known[0].diagnostic_purpose=='DIAGNOSTIC_ONLY'


@pytest.mark.pit
def test_stale_market_data_remains_hold(world):
    from xevent.evaluation.fixture import revised
    w=world; run=w['run']; ws=windows(w['calendar'],run.package_available_at)
    start=next_session(w['calendar'],run.package_available_at+timedelta(seconds=60))
    quote(w,'STALE_ENTRY',start,100.0,quality='STALE')
    quote(w,'STALE_EXIT',ws[-1].end,105.0)
    out=w['evaluation'].settle(vr(run),as_of=w['clock']())
    assert all(o.reference_return is None for o in out)
    qs=w['labels'].history(as_of=w['clock'](),kind='SampleQuality')
    assert any('STALE_QUOTE' in q.quality_reasons for q in qs)


@pytest.mark.pit
def test_future_settle_incident_is_reported(world):
    w=world
    with pytest.raises(ValueError,match='SETTLEMENT_FUTURE'):
        w['evaluation'].settle(vr(w['run']),as_of=w['clock']()+timedelta(days=10))
    r=report(w['evaluation'],'PIT_REPORT',(vr(w['run']),vr(w['empty_run'])),as_of=w['clock']())
    assert r.health.pit_violation_count==1 and r.health.health=='HOLD'


@pytest.mark.pit
def test_late_quotes_not_retroactive_simulated_fills(world):
    w=world; run=w['run']; ws=windows(w['calendar'],run.package_available_at)
    entry=next_session(w['calendar'],run.package_available_at+timedelta(seconds=60))
    w['clock'].value=ws[-1].end+timedelta(minutes=1)
    quote(w,'LATE_ENTRY',entry,100.0)
    quote(w,'LATE_EXIT',ws[-1].end,110.0)
    out=w['evaluation'].settle(vr(run),as_of=w['clock']())
    final=[o for o in out if o.window.name=='T3_CLOSE' and o.reference_return is not None]
    assert final and all(o.simulation.simulated_return is None for o in final)


@pytest.mark.pit
@pytest.mark.parametrize('mode,kind',[('HISTORICAL_REPLAY','HISTORICAL_RECOMPUTE'),('PUBLIC_PIT_RESEARCH','PUBLIC_PIT_REPORT')])
def test_historical_package_reports_remain_separate(world,tmp_path,mode,kind):
    from xevent.ledger.store import Ledger
    from xevent.ranking.engine import RankingEngine
    from xevent.ranking.contracts import RankRequest
    w=world; target=tmp_path/'historical-features.sqlite'
    with sqlite3.connect(w['ledger'].path) as source, sqlite3.connect(target) as out: source.backup(out)
    features=Ledger(target,clock=w['clock'])
    try:
        ranking=RankingEngine(features); policy=ranking.policy('HIST_POLICY',ranking_mode='HISTORICAL_REPLAY')
        package=ranking.build('HIST_EMPTY',RankRequest(snapshot_ref=w['package'].request.snapshot_ref,history_refs=(),
            policy_ref=vr(policy),ranking_mode='HISTORICAL_REPLAY',as_of=w['clock']()))
        start=w['clock']()+timedelta(seconds=1)
        plan=w['evaluation'].plan('HIST_PLAN',calendar_ref=vr(w['calendar']),rank_policy_ref=vr(policy),epoch='HIST_EPOCH',
            registration_start=start.isoformat(),registration_end=(start+timedelta(days=1)).isoformat(),evaluation_mode=mode)
        w['clock'].value=start+timedelta(seconds=1)
        run=w['evaluation'].register('HIST_RUN',features=features,package_ref=vr(package),plan_ref=vr(plan))
        assert run.forward_identity=='HISTORICAL_RECOMPUTE'
        result=report(w['evaluation'],'HIST_REPORT',(vr(run),),as_of=w['clock']())
        assert result.report_kind==kind and result.formal_live_alpha is False
        with pytest.raises(ValueError,match='MODE_EPOCH_ISOLATION'):
            report(w['evaluation'],'MIXED_REPORT',(vr(run),vr(w['run'])),as_of=w['clock']())
    finally: features.close()


@pytest.mark.pit
def test_durable_commit_recovery_never_backdates_outcome(world):
    w=world; ws=windows(w['calendar'],w['run'].package_available_at)
    w['clock'].value=ws[-1].end+timedelta(minutes=1)
    at=w['clock']()
    def fault(stage):
        if stage=='after_commit': raise RuntimeError('crash after data commit')
    w['labels'].fault=fault
    with pytest.raises(RuntimeError): w['evaluation'].settle(vr(w['run']),as_of=at)
    cutoff=w['clock']()
    assert not w['labels'].history(as_of=cutoff,kind='Outcome')
    w['labels'].fault=lambda stage:None
    w['clock'].value+=timedelta(minutes=2)
    w['labels'].recover()
    outcomes=w['labels'].history(as_of=w['clock'](),kind='Outcome')
    assert outcomes and all(o.available_at>cutoff for o in outcomes)
    assert not w['labels'].history(as_of=cutoff,kind='Outcome')


def test_zero_created_runs_report_missing_schedule(world):
    w=world; old=w['evaluation_plan']; start=w['clock']()+timedelta(seconds=1)
    plan=w['evaluation'].plan('NO_CREATED_RUNS',calendar_ref=old.calendar_ref,rank_policy_ref=old.rank_policy_ref,epoch='NO_RUNS',
        registration_start=start.isoformat(),registration_end=(start+timedelta(days=1)).isoformat(),expected_runs=1)
    r=report(w['evaluation'],'NO_RUNS_REPORT',(),as_of=w['clock'](),plan_ref=vr(plan))
    assert r.health.runs_expected==1 and r.health.runs_created==0 and r.health.health=='HOLD'
    assert r.statistics and all(s.total_frozen==0 and s.coverage_rate is None for s in r.statistics)


@pytest.mark.pit
def test_same_event_across_runs_does_not_become_independent_clusters():
    from xevent.evaluation.engine import merge_cluster_tokens
    tokens={('run1','c1'):('EVENT:A','ORIGIN:X'),('run2','c2'):('EVENT:A','ORIGIN:Y'),
        ('run3','c3'):('EVENT:B','ORIGIN:Y'),('run4','c4'):('EVENT:C','ORIGIN:Z')}
    groups=merge_cluster_tokens(tokens)
    assert groups[('run1','c1')]==groups[('run2','c2')]==groups[('run3','c3')]
    assert groups[('run4','c4')]!=groups[('run1','c1')]
    assert groups==merge_cluster_tokens(dict(reversed(list(tokens.items()))))


def test_unresolved_event_kept_in_denominator_not_independent_cluster():
    from xevent.evaluation.engine import merge_cluster_tokens
    cluster=merge_cluster_tokens({'missing':('SECURITY:UNKNOWN_EVENT',)})['missing']
    s=summarize('WATCH','T1_CLOSE',statistic_samples([0.1]*10,[cluster]*10),EvaluationRules())
    assert s.total_frozen==10 and s.sample_n==10 and s.unresolved_event_sample_n==10
    assert s.event_cluster_n==0 and s.settled_event_cluster_n==0 and s.interval is None
    assert 'HOLD_EVENT_CLUSTER_IDENTIFICATION' in s.hold_reasons


@pytest.mark.pit
def test_transitive_origin_links_without_intermediate_candidates_are_order_independent():
    from types import SimpleNamespace
    from xevent.contracts.models import EventVersion, EvidenceVersion
    from xevent.ledger.contracts import OriginClusterVersion
    from xevent.evaluation.engine import frozen_clusters
    candidates=[]; view={}
    for name,origin in [('A','a'),('E','e')]:
        evidence=EvidenceVersion.model_construct(object_id='evidence'+name,version=1,origin_cluster_id=origin)
        event=EventVersion.model_construct(object_id='event'+name,version=1,evidence_refs=(vr(evidence),))
        candidates.append(SimpleNamespace(object_id=name,event_ref=vr(event)))
        view[(evidence.object_id,1)]=evidence
        view[(event.object_id,1)]=event
    for i,members in enumerate([('b','c'),('a','b'),('c','d'),('d','e')]):
        link=OriginClusterVersion.model_construct(object_id='link'+str(i),version=1,
            verification='KNOWN_ORIGIN',member_origin_ids=members)
        view[(link.object_id,1)]=link
    result=frozen_clusters(candidates,view)
    assert result[0]['A']==result[0]['E']
    assert result==frozen_clusters(list(reversed(candidates)),dict(reversed(list(view.items()))))
    assert all({'ORIGIN:'+x for x in 'abcde'} <= scope for scope in result[2].values())
