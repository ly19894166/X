"""All-frozen denominators and event-cluster uncertainty; no calibrated Alpha claims."""
from collections import defaultdict
from random import Random
from statistics import mean, median
from pydantic import TypeAdapter
from ..contracts.common import UTCDateTime
from ..ledger.store import ref
from .contracts import *
from .engine import vr, key, merge_cluster_tokens

HOLDS=('HOLD_MODEL_PROVIDER_LIVE','HOLD_MODEL_USAGE_COST_UNVERIFIED','HOLD_MARKET_DATA_PROVIDER_LIVE',
    'HOLD_REAL_FORWARD_QUALIFICATION','HOLD_PRICING_POLICY_CALIBRATION','HOLD_RANK_POLICY_CALIBRATION',
    'HOLD_HISTORICAL_UNIVERSE_COVERAGE','HOLD_REAL_COMPANY_EXPOSURE_COVERAGE','HOLD_PRE_1992_CALENDAR',
    'HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION','HOLD_EVALUATION_POLICY_CALIBRATION','HOLD_REAL_COST_QUALIFICATION',
    'HOLD_ABLATION_NO_RED_TEAM','HOLD_ABLATION_NO_NEXT_BUYER')


def interval(cluster_returns,rules):
    """Equal event-cluster weighting; all paths stay visible in candidate statistics."""
    values=[mean(cluster_returns[k]) for k in sorted(cluster_returns)]
    if len(values)<2: return None
    rng=Random(rules.bootstrap_seed)
    draws=sorted(mean(rng.choices(values,k=len(values))) for _ in range(rules.bootstrap_replicates))
    return (draws[int(0.025*(len(draws)-1))],draws[int(0.975*(len(draws)-1))])


def summarize(group,window,samples,rules):
    returns=[]; simulated=[]; clusters=defaultdict(list); mfes=[]; maes=[]
    counts=defaultdict(int)
    for run,c,cluster,o,q in samples:
        if q is None: counts['unsettled']+=1
        else: counts[{'QUALIFIED':'settled','PARTIAL':'partially_settled','UNSETTLED':'unsettled',
            'MARKET_DATA_HOLD':'data_hold','EXECUTION_HOLD':'execution_hold','PIT_HOLD':'pit_hold'}[q.quality]]+=1
        if o is not None and q is not None and q.reference_eligible and o.reference_return is not None:
            returns.append(o.reference_return)
            if not cluster.startswith('UNRESOLVED:'): clusters[cluster].append(o.reference_return)
        if o is not None and q is not None and q.simulated_eligible and o.simulation.simulated_return is not None:
            simulated.append(o.simulation.simulated_return)
        if o is not None and o.mfe is not None: mfes.append(o.mfe); maes.append(o.mae)
    total=len(samples); coverage=len(returns)/total if total else None
    all_clusters={s[2] for s in samples if not s[2].startswith('UNRESOLVED:')}
    unresolved=sum(s[2].startswith('UNRESOLVED:') for s in samples)
    holds=[]
    if unresolved: holds.append('HOLD_EVENT_CLUSTER_IDENTIFICATION')
    ci=interval(clusters,rules)
    if ci is None: holds.append('HOLD_STATISTICAL_INTERVAL')
    if len(returns)<rules.min_candidates or len(clusters)<rules.min_clusters or coverage is None or coverage<rules.min_coverage:
        holds.append('FORWARD_HOLD_INSUFFICIENT_SAMPLE')
    result='INSUFFICIENT_SAMPLE' if holds else 'NEGATIVE_EDGE' if mean(returns)<0 else 'INCONCLUSIVE'
    if counts['pit_hold']: result='DATA_QUALITY_HOLD'
    return GroupStatistic(group=group,window=window,total_frozen=total,**{k:counts[k] for k in
        ('settled','partially_settled','unsettled','data_hold','execution_hold','pit_hold')},sample_n=len(returns),
        event_cluster_n=len(all_clusters),settled_event_cluster_n=len(clusters),unresolved_event_sample_n=unresolved,
        repeated_security_path_count=total-len({(s[0].object_id,s[1].security_ref.object_id) for s in samples}),
        coverage_rate=coverage,settlement_rate=len(simulated)/total if total else None,
        positive_return_rate=sum(x>0 for x in returns)/len(returns) if returns else None,
        negative_return_rate=sum(x<0 for x in returns)/len(returns) if returns else None,
        mean_return=mean(returns) if returns else None,median_return=median(returns) if returns else None,
        simulated_mean_return=mean(simulated) if simulated else None,mfe=mean(mfes) if mfes else None,mae=mean(maes) if maes else None,
        cluster_mean_return=mean([mean(xs) for xs in clusters.values()]) if clusters else None,interval=ci,conclusion=result,hold_reasons=holds)


def report(engine,identity,run_refs,*,as_of,version=1,revision_reason=None,plan_ref=None):
    at=TypeAdapter(UTCDateTime).validate_python(as_of)
    if at>engine.ledger.now(): raise ValueError('REPORT_PIT')
    if len(set(run_refs))!=len(run_refs) or (not run_refs and plan_ref is None): raise ValueError('REPORT_RUNS_REQUIRED_UNIQUE')
    runs=sorted((engine.load(r,ResearchRunManifest,at) for r in run_refs),key=key)
    if runs and len({(r.evaluation_mode,r.epoch,key(r.evaluation_plan_ref)) for r in runs})!=1: raise ValueError('REPORT_MODE_EPOCH_ISOLATION')
    if runs and plan_ref is not None and runs[0].evaluation_plan_ref!=plan_ref: raise ValueError('REPORT_PLAN_MISMATCH')
    plan=engine.load(runs[0].evaluation_plan_ref if runs else plan_ref,EvaluationPlan,at)
    # Reports cannot cherry-pick a subset of registered runs within this plan/epoch.
    view=engine.ledger.history(as_of=at)
    expected={key(r) for r in view if isinstance(r,ResearchRunManifest) and r.evaluation_plan_ref==vr(plan)}
    if {key(r) for r in runs}!=expected: raise ValueError('REPORT_RUN_OMISSION')
    outcomes={}; qualities={}
    for o in view:
        table=outcomes if isinstance(o,Outcome) else qualities if isinstance(o,SampleQuality) else None
        if table is not None:
            k=(key(o.research_run_ref),key(o.candidate_ref),o.window.name)
            if k not in table or o.version>table[k].version: table[k]=o
    archives={key(r):engine.load(r.archive_ref,FrozenFeatureArchive,at) for r in runs}
    cluster_ids=merge_cluster_tokens({(r.object_id,cid):tokens for r in runs
        for cid,tokens in archives[key(r)].candidate_cluster_tokens.items()})
    grouped=defaultdict(list)
    for group in ('ALPHA1','ALPHA2','BETA','WATCH','OVERPRICED','REJECT','ALL_FROZEN','HOLD',*plan.rules.baselines,*plan.rules.ablations):
        for window in plan.rules.windows: grouped[(group,window)]=[]
    for run in runs:
        archive=archives[key(run)]
        for group,members in run.eligible_evaluation_groups.items():
            for window in plan.rules.windows:
                bucket=grouped[(group,window)] # Empty lists are formal report rows.
                for c in archive.candidates:
                    if vr(c) not in members: continue
                    k=(key(run),key(c),window)
                    bucket.append((run,c,cluster_ids[(run.object_id,c.object_id)],outcomes.get(k),qualities.get(k)))
    stats=[summarize(g,w,samples,plan.rules) for (g,w),samples in sorted(grouped.items())]
    baselines={s.window:s for s in stats if s.group=='BASELINE_ALL_ECONOMIC_VALID'}
    for i,s in enumerate(stats):
        baseline=baselines.get(s.window)
        if s.group=='ALPHA1' and not s.hold_reasons and baseline and baseline.mean_return is not None and s.mean_return is not None:
            if s.mean_return>=0 and s.mean_return<=baseline.mean_return:
                stats[i]=s.model_copy(update={'conclusion':'NO_EDGE_OBSERVED'})
    relevant_outcomes=[o for k,o in outcomes.items() if k[0] in {key(r) for r in runs}]
    relevant_quality=[q for k,q in qualities.items() if k[0] in {key(r) for r in runs}]
    total=sum(r.candidate_total for r in runs)*len(plan.rules.windows)
    incidents=[o for o in view if isinstance(o,EvaluationIncident) and key(o.research_run_ref) in {key(r) for r in runs}]
    pit=sum(q.quality=='PIT_HOLD' for q in relevant_quality)+len(incidents)
    created=len(runs)
    health=ForwardHealth(runs_expected=plan.expected_runs,runs_created=created,
        runs_settled=sum(all((key(r),key(c),w) in outcomes for c in archives[key(r)].candidates for w in plan.rules.windows) for r in runs),
        runs_late=len({key(o.research_run_ref) for o in relevant_outcomes if o.late}),candidate_total=sum(r.candidate_total for r in runs),
        outcome_total=len(relevant_outcomes),quote_coverage=sum(q.reference_eligible for q in relevant_quality)/total if total else None,
        calendar_coverage=1.0 if runs else None,settlement_coverage=sum(q.simulated_eligible for q in relevant_quality)/total if total else None,
        stale_data_count=sum('STALE_QUOTE' in q.quality_reasons for q in relevant_quality),
        missing_data_count=sum(any('MISSING' in x for x in q.quality_reasons) for q in relevant_quality),
        execution_hold_count=sum(q.quality=='EXECUTION_HOLD' for q in relevant_quality),
        empty_list_rate=sum(r.empty_opportunity_list for r in runs)/created if created else None,
        pit_violation_count=pit,health='HOLD' if pit or created<plan.expected_runs else 'ENGINEERING_ONLY')
    kinds={'ENGINEERING_FIXTURE':'ENGINEERING_REPORT','MOCK_FORWARD':'MOCK_FORWARD_REPORT',
        'PUBLIC_PIT_RESEARCH':'PUBLIC_PIT_REPORT','HISTORICAL_REPLAY':'HISTORICAL_RECOMPUTE','REAL_FORWARD':'REAL_FORWARD_REPORT'}
    holds=sorted(set(HOLDS)|{h for s in stats for h in s.hold_reasons})
    payload=dict(as_of=at.isoformat(),evaluation_mode=plan.evaluation_mode,provenance='全部预注册窗口、分组与失败分母；区间按事件簇等权重采样',
        research_run_refs=[ref(r) for r in runs],evaluation_plan_ref=ref(plan),outcome_refs=[ref(o) for o in sorted(relevant_outcomes,key=key)],
        epoch=plan.epoch,report_kind=kinds[plan.evaluation_mode],statistics=[s.model_dump(mode='json') for s in stats],
        health=health.model_dump(mode='json'),hold_reasons=holds,revision_reason=revision_reason)
    deps=[ref(plan),*[ref(r) for r in runs],*[ref(a) for a in archives.values()],*[ref(o) for o in relevant_outcomes],*[ref(q) for q in relevant_quality],*[ref(i) for i in incidents]]
    return engine.publish(EvaluationReport,identity,payload,inputs=deps,version=version)
