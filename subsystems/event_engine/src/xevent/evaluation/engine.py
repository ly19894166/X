"""One-way freeze -> labels. Never reruns ranking or writes the feature ledger."""
from collections import Counter
from datetime import timedelta
from pathlib import Path
from pydantic import TypeAdapter
from ..contracts.common import UTCDateTime, VersionRef
from ..contracts.bundle import content_digest
from ..contracts.models import EventVersion, EvidenceVersion
from ..ledger.contracts import OriginClusterVersion
from ..ledger.store import digest, ref
from ..ranking.contracts import OpportunityPackage, RankManifest, RankSnapshot, RankPolicy
from .contracts import *
from .store import Publisher
from .calendar import validate_calendar, windows, next_session, trading_day, diagnostic_grid


def vr(o): return VersionRef(**ref(o))
def key(o): return o.object_id,o.version
def raw(o): return o.model_dump(mode='json')


def merge_cluster_tokens(tokens):
    groups=[]
    for cid in sorted(tokens):
        ids={cid}; scope=set(tokens[cid]); merged=[]
        for old_ids,old_scope in groups:
            if scope&old_scope: ids|=old_ids; scope|=old_scope
            else: merged.append((old_ids,old_scope))
        groups=merged+[(ids,scope)]
    return {cid:('CLUSTER:' if any(t.startswith('EVENT:') for t in scope) else 'UNRESOLVED:')+digest(sorted(scope))[:24]
        for ids,scope in groups for cid in ids}


def frozen_clusters(candidates,view):
    """Conservative connected components using only pre-freeze Event/Evidence/Origin IDs."""
    tokens={}; used={}
    for c in candidates:
        scope={'SECURITY:'+c.security_ref.object_id} if c.event_ref is None else {'EVENT:'+c.event_ref.object_id}
        if c.event_ref:
            e=view[key(c.event_ref)]; used[key(e)]=e
            if not isinstance(e,EventVersion): raise ValueError('EVENT_REFERENCE')
            for r in e.evidence_refs:
                evidence=view[key(r)]; used[key(evidence)]=evidence
                scope.add('ORIGIN:'+evidence.origin_cluster_id)
        tokens[c.object_id]=scope
    origin_links=[o for o in view.values()
        if isinstance(o,OriginClusterVersion) and o.verification=='KNOWN_ORIGIN']
    changed=True
    while changed:
        changed=False
        for o in origin_links:
            members={'ORIGIN:'+i for i in o.member_origin_ids}
            for scope in tokens.values():
                if scope&members:
                    used[key(o)]=o
                    if not members <= scope:
                        scope.update(members)
                        changed=True
    return merge_cluster_tokens(tokens),tuple(vr(used[k]) for k in sorted(used) if isinstance(used[k],(EventVersion,OriginClusterVersion))),tokens


def group_members(candidates,plan):
    groups={g:tuple(vr(c) for c in candidates if c.candidate_grade==g) for g in ('ALPHA1','ALPHA2','BETA','WATCH','OVERPRICED','REJECT')}
    groups['ALL_FROZEN']=tuple(vr(c) for c in candidates)
    groups['HOLD']=tuple(vr(c) for c in candidates if c.processing_state=='HOLD')
    economic=tuple(vr(c) for c in candidates if c.world=='ECONOMIC' and c.processing_state in ('VALID','WATCH','OVERPRICED')
        and c.final_choice in ('TARGET','ALT') and c.research_status=='MOCK_PASS' and c.mapping_state not in ('INVALID','UNKNOWN'))
    for name in plan.rules.baselines:
        groups[name]=economic if name=='BASELINE_ALL_ECONOMIC_VALID' else groups[name.removeprefix('BASELINE_')]
    for name in plan.rules.ablations:
        if name=='NO_RANKING': groups[name]=economic
        else:
            # Pre-registered eligibility ablation, not a reconstructed economic fact or rewritten grade.
            groups[name]=tuple(vr(c) for c in candidates if vr(c) in economic and c.red_team_status not in ('INCOMPLETE','TARGET_INVALIDATED','NULL_PREFERRED')
                and c.thesis_strength in ('HIGH','VERY_HIGH') and c.next_buyer_status=='SUPPORTED')
    return groups


class EvaluationEngine(Publisher):
    def load(self,r,cls,at=None):
        o=self.ledger.get(r.object_id,r.version)
        if not isinstance(o,cls) or (at is not None and o.available_at>at): raise ValueError('EVALUATION_REFERENCE_PIT')
        return o

    def plan(self,identity,*,calendar_ref,rank_policy_ref,epoch,registration_start,registration_end,
             expected_runs=1,rules=None,evaluation_mode='ENGINEERING_FIXTURE',version=1,revision_reason=None):
        cal=self.load(calendar_ref,SettlementCalendar,self.ledger.now()); validate_calendar(cal)
        return self.publish(EvaluationPlan,identity,dict(calendar_ref=ref(calendar_ref),rank_policy_ref=ref(rank_policy_ref),epoch=epoch,
            registration_start=registration_start,registration_end=registration_end,expected_runs=expected_runs,
            rules=raw(EvaluationRules.model_validate(rules or {})),evaluation_mode=evaluation_mode,revision_reason=revision_reason),
            inputs=[ref(cal)],version=version)

    def register(self,identity,*,features,package_ref,plan_ref):
        if Path(features.path).resolve()==self.ledger.path: raise ValueError('LABEL_FEATURE_DATABASE_ISOLATION')
        now=self.ledger.now(); plan=self.load(plan_ref,EvaluationPlan,now)
        if plan.evaluation_mode=='REAL_FORWARD': raise ValueError('HOLD_REAL_FORWARD_QUALIFICATION')
        package=features.get(package_ref.object_id,package_ref.version)
        if not isinstance(package,OpportunityPackage) or package.available_at>now: raise ValueError('PACKAGE_PIT')
        allowed={'ENGINEERING_FIXTURE':'ENGINEERING_FIXTURE','MOCK_FORWARD':'MOCK_FORWARD',
            'HISTORICAL_REPLAY':'HISTORICAL_REPLAY','PUBLIC_PIT_RESEARCH':'HISTORICAL_REPLAY'}
        if package.ranking_mode!=allowed[plan.evaluation_mode]: raise ValueError('EVALUATION_MODE_ISOLATION')
        if package.request.policy_ref!=plan.rank_policy_ref: raise ValueError('POLICY_EPOCH_MISMATCH')
        policy=features.get(plan.rank_policy_ref.object_id,plan.rank_policy_ref.version)
        if not isinstance(policy,RankPolicy) or policy.available_at>plan.available_at: raise ValueError('PLAN_POLICY_PIT')
        if not plan.registration_start<=now<plan.registration_end: raise ValueError('PLAN_REGISTRATION_WINDOW')
        cal=self.load(plan.calendar_ref,SettlementCalendar,now)
        schedule=windows(cal,package.available_at)
        if now>=min(w.end for w in schedule): raise ValueError('RUN_REGISTRATION_AFTER_OUTCOME')
        earliest=next_session(cal,package.available_at+timedelta(seconds=plan.rules.delay_seconds))
        if now>=earliest: raise ValueError('RUN_REGISTRATION_AFTER_ENTRY')
        view={key(o):o for o in features.history(as_of=package.available_at)}
        manifest=view[key(package.manifest_ref)]; snapshot=view[key(package.rank_snapshot_ref)]
        candidates=tuple(view[key(r)] for r in package.candidate_refs)
        clusters,cluster_refs,cluster_tokens=frozen_clusters(candidates,view)
        closure={}
        def visit(o):
            if key(o) in closure: return
            if o.content_hash!=content_digest(o): raise ValueError('FEATURE_HASH')
            closure[key(o)]=o
            for r in o.input_version_refs: visit(view[key(r)])
        visit(package)
        for r in cluster_refs: visit(view[key(r)])
        archive_id=identity+':FEATURES'
        common=dict(as_of=now.isoformat(),evaluation_mode=plan.evaluation_mode,provenance='冻结全部候选及当时可知事件簇；不读取未来标签',policy_version=POLICY)
        archive=dict(**common,package=raw(package),manifest=raw(manifest),snapshot=raw(snapshot),candidates=[raw(c) for c in candidates],
            feature_hashes={f'{k[0]}@{k[1]}':o.content_hash for k,o in closure.items()},candidate_clusters=clusters,
            candidate_cluster_tokens={cid:sorted(xs) for cid,xs in cluster_tokens.items()},
            event_cluster_refs=[ref(r) for r in cluster_refs],source_database_identity=digest(str(features.path)))
        data=dict(**common,shadow_run_id=identity,archive_ref=dict(object_id=archive_id,version=1),opportunity_package_ref=ref(package),
            rank_manifest_ref=ref(manifest),rank_snapshot_ref=ref(snapshot),evaluation_plan_ref=ref(plan),feature_cutoff=package.as_of.isoformat(),
            package_available_at=package.available_at.isoformat(),ranking_mode=package.ranking_mode,research_universe_ref=ref(package.request.snapshot_ref),
            universe_total=manifest.universe_total,candidate_total=manifest.total,grade_counts=dict(Counter(c.candidate_grade for c in candidates)),
            hold_count=manifest.hold,empty_opportunity_list=package.empty_opportunity_list,
            eligible_evaluation_groups={g:[ref(r) for r in rs] for g,rs in group_members(candidates,plan).items()},
            event_cluster_refs=[ref(r) for r in cluster_refs],security_refs=[dict(object_id=k[0],version=k[1]) for k in sorted({key(c.security_ref) for c in candidates})],
            manifest_hash=digest([archive,raw(plan)]),epoch=plan.epoch,
            forward_identity='HISTORICAL_RECOMPUTE' if plan.evaluation_mode in ('HISTORICAL_REPLAY','PUBLIC_PIT_RESEARCH') else 'ORIGINAL_REGISTRATION')
        def build(conn,v,batch):
            if any(isinstance(o,ResearchRunManifest) and o.opportunity_package_ref==package_ref
                and o.evaluation_mode==plan.evaluation_mode and o.epoch==plan.epoch for o in v.values()): raise ValueError('DUPLICATE_FROZEN_RUN')
            self.ledger._put(conn,batch,'FrozenFeatureArchive',archive_id,1,archive)
            self.ledger._put(conn,batch,'ResearchRunManifest',identity,1,data,[ref(plan),dict(object_id=archive_id,version=1)])
        self.ledger._write('P10:REGISTER:'+identity,digest([ref(package_ref),package.content_hash,ref(plan_ref),plan.content_hash,str(features.path)]),build)
        return self.ledger.get(identity,1)

    def quote_reasons(self,q,calendar,security_ref,mode):
        o=q.observation; reasons=[]
        if q.evaluation_mode!=mode: reasons.append('QUOTE_MODE_MISMATCH')
        expected={'ENGINEERING_FIXTURE':'ENGINEERING_FIXTURE','MOCK_FORWARD':'MOCK_FORWARD',
            'PUBLIC_PIT_RESEARCH':'HISTORICAL_REPLAY','HISTORICAL_REPLAY':'HISTORICAL_REPLAY','REAL_FORWARD':'REAL_FORWARD'}[mode]
        if any(x.pricing_mode!=expected for x in (o,q.provider_qualification,q.session,q.adjustment)):
            reasons.append('QUOTE_MODE_MISMATCH')
        if o.instrument_ref!=security_ref: reasons.append('QUOTE_SECURITY_MISMATCH')
        if o.observation_type!='PRICE' or o.unit!='CURRENCY_PER_UNIT' or o.currency!='CNY': reasons.append('FX_UNKNOWN')
        if o.quality_status!='QUALIFIED' or o.value is None: reasons.append('MISSING_MARKET_DATA')
        if o.staleness_seconds>0 or o.quality_status=='STALE': reasons.append('STALE_QUOTE')
        if q.provider_qualification.qualification_status!='PROVIDER_QUALIFIED': reasons.append('PROVIDER_HOLD')
        if o.window.start!=o.window.end or not trading_day(calendar,o.window.end): reasons.append('CALENDAR_UNKNOWN')
        if not any(w.start<=o.window.end<=w.end for w in q.session.intervals): reasons.append('CALENDAR_UNKNOWN')
        if o.adjustment_type!='UNADJUSTED': reasons.append('ADJUSTMENT_COMPARABILITY_HOLD')
        return reasons

    def settle(self,run_ref,*,as_of,version=1,revision_reason=None):
        at=TypeAdapter(UTCDateTime).validate_python(as_of)
        if at>self.ledger.now():
            run=self.load(run_ref,ResearchRunManifest,self.ledger.now())
            self.publish(EvaluationIncident,run.object_id+':PIT:'+digest(at.isoformat())[:16],dict(
                evaluation_mode=run.evaluation_mode,research_run_ref=ref(run),category='PIT_VIOLATION',diagnostic_code='SETTLEMENT_FUTURE'),inputs=[ref(run)])
            raise ValueError('SETTLEMENT_FUTURE')
        run=self.load(run_ref,ResearchRunManifest,at); plan=self.load(run.evaluation_plan_ref,EvaluationPlan,at)
        archive=self.load(run.archive_ref,FrozenFeatureArchive,at); cal=self.load(plan.calendar_ref,SettlementCalendar,at)
        schedule=windows(cal,run.package_available_at)
        if version>1 and not revision_reason: raise ValueError('REVISION_REASON_REQUIRED')
        def build(conn,view,batch):
            visible=[o for o in view.values() if isinstance(o,OutcomeQuote) and o.available_at<=at and o.evaluation_mode==run.evaluation_mode]
            # Current known publication per exact timestamp/source scope; ties fail closed, not first-row wins.
            grouped={}
            for q in visible:
                o=q.observation; scope=(key(o.instrument_ref),o.window.end,o.provider,key(o.source_ref))
                grouped.setdefault(scope,[]).append(q)
            quotes=[]
            for qs in grouped.values():
                latest=max(q.available_at for q in qs); winners=[q for q in qs if q.available_at==latest]
                if len(winners)>1: raise ValueError('OUTCOME_QUOTE_SCOPE_AMBIGUITY')
                quotes.append(winners[0])
            for c in archive.candidates:
                candidate_quotes=[q for q in quotes if q.observation.instrument_ref==c.security_ref]
                target=next_session(cal,run.package_available_at+timedelta(seconds=plan.rules.delay_seconds))
                entries=sorted((q for q in candidate_quotes if target<=q.observation.window.end<=target+timedelta(seconds=plan.rules.max_entry_wait_seconds)
                    and q.observation.available_at>=run.package_available_at and q.available_at>=run.available_at),key=lambda q:(q.observation.window.end,q.object_id))
                entry=entries[0] if entries else None
                if len(entries)>1 and entries[0].observation.window.end==entries[1].observation.window.end: raise ValueError('ENTRY_QUOTE_AMBIGUITY')
                for window in schedule:
                    oid=run.object_id+':'+c.object_id+':'+window.name
                    quality_id=oid+':QUALITY'
                    oldq=max((o for o in view.values() if o.object_id==quality_id),key=lambda o:o.version,default=None)
                    if version!=(oldq.version+1 if oldq else 1): raise ValueError('SETTLEMENT_APPEND_ONLY')
                    old=max((o for o in view.values() if o.object_id==oid),key=lambda o:o.version,default=None)
                    exits=[q for q in candidate_quotes if q.observation.window.end==window.end]
                    if len(exits)>1: raise ValueError('EXIT_QUOTE_AMBIGUITY')
                    exit_quote=exits[0] if exits else None
                    reasons=[]
                    if window.end>at: reasons.append('WINDOW_NOT_FINISHED')
                    if entry is None: reasons.append('MISSING_ENTRY_QUOTE')
                    if exit_quote is None: reasons.append('MISSING_EXIT_QUOTE')
                    if entry and entry.observation.window.end>window.end: reasons.append('ENTRY_AFTER_WINDOW')
                    if entry and exit_quote:
                        a,b=entry.observation,exit_quote.observation
                        if (a.provider,a.source_ref,a.unit,a.currency,a.adjustment_ref)!=(b.provider,b.source_ref,b.unit,b.currency,b.adjustment_ref):
                            reasons.append('QUOTE_COMPARABILITY_HOLD')
                    for q in (entry,exit_quote):
                        if q: reasons.extend(self.quote_reasons(q,cal,c.security_ref,run.evaluation_mode))
                    reference=None
                    if not reasons: reference=exit_quote.observation.value/entry.observation.value-1
                    es=entry.entry_executability if entry else 'QUOTE_MISSING'
                    xs=exit_quote.exit_executability if exit_quote else 'QUOTE_MISSING'
                    entry_day=trading_day(cal,entry.observation.window.end) if entry else None
                    t1=bool(entry_day and entry_day<window.trading_date)
                    simulation_reasons=[s for s in (es,xs) if s!='EXECUTABLE']
                    if any(q and (q.available_at-q.observation.window.end).total_seconds()>plan.rules.max_quote_latency_seconds for q in (entry,exit_quote)):
                        simulation_reasons.append('QUOTE_NOT_AVAILABLE_FOR_SIMULATED_EXECUTION')
                    if not t1: simulation_reasons.append('T_PLUS_ONE_RESTRICTION')
                    simulated=None
                    if reference is not None and not simulation_reasons:
                        r=plan.rules
                        simulated=(exit_quote.observation.value*(1-r.slippage)*(1-r.commission-r.tax-r.other_cost))/(
                            entry.observation.value*(1+r.slippage)*(1+r.commission+r.other_cost))-1
                    quality='UNSETTLED' if 'WINDOW_NOT_FINISHED' in reasons else 'MARKET_DATA_HOLD' if reasons else 'QUALIFIED' if simulated is not None else 'PARTIAL'
                    if not reasons and any(s!='EXECUTABLE' for s in (es,xs)): quality='EXECUTION_HOLD'
                    if not reasons and 'QUOTE_NOT_AVAILABLE_FOR_SIMULATED_EXECUTION' in simulation_reasons: quality='EXECUTION_HOLD'
                    deps=[ref(run),ref(plan),ref(archive),ref(cal),*[ref(q) for q in (entry,exit_quote) if q],*([ref(oldq)] if oldq else [])]
                    common=dict(as_of=at.isoformat(),evaluation_mode=run.evaluation_mode,policy_version=POLICY,
                        provenance='固定窗口离线结果；全样本保留；模拟不等于实盘收益',revision_reason=revision_reason)
                    quality_data=dict(**common,research_run_ref=ref(run),candidate_ref=ref(c),window=raw(window),quality=quality,
                        quality_reasons=sorted(set(reasons+simulation_reasons)),reference_eligible=reference is not None,simulated_eligible=simulated is not None)
                    self.ledger._put(conn,batch,'SampleQuality',quality_id,version,quality_data,deps)
                    if window.end>at: continue # Only pending quality, never a future Outcome.
                    diagnostics=[q for q in candidate_quotes if entry and entry.observation.window.end<=q.observation.window.end<=window.end
                        and not self.quote_reasons(q,cal,c.security_ref,run.evaluation_mode)]
                    grid=diagnostic_grid(cal,entry.observation.window.end,window.end) if entry else ()
                    complete=bool(reference is not None and grid and set(grid)=={q.observation.window.end for q in diagnostics})
                    returns=[q.observation.value/entry.observation.value-1 for q in diagnostics] if complete else []
                    sim=ExecutionSimulation(entry_status=es,exit_status=xs,settlement_kind='REALIZABLE_SETTLEMENT' if simulated is not None else 'OBSERVATIONAL_OUTCOME',
                        t_plus_one_satisfied=t1,simulated_return=simulated,cost_plan_ref=vr(plan),reason_codes=simulation_reasons+reasons)
                    data=dict(**common,research_run_ref=ref(run),candidate_ref=ref(c),window=raw(window),plan_ref=ref(plan),
                        entry_quote_ref=ref(entry) if entry else None,exit_quote_ref=ref(exit_quote) if exit_quote else None,
                        observation_refs=[ref(q) for q in diagnostics],reference_return=reference,simulation=raw(sim),
                        quality_ref=dict(object_id=quality_id,version=version),mfe=max(returns) if returns else None,mae=min(returns) if returns else None,
                        diagnostic_reason=None if complete else 'DIAGNOSTIC_GRID_INCOMPLETE',late=at>window.end+timedelta(seconds=plan.rules.late_tolerance_seconds))
                    outcome_version=old.version+1 if old else 1
                    self.ledger._put(conn,batch,'Outcome',oid,outcome_version,data,[*deps,dict(object_id=quality_id,version=version),
                        *[ref(q) for q in diagnostics],*([ref(old)] if old else [])])
        self.ledger._write('P10:SETTLE:'+run.object_id+':'+str(version),digest([ref(run_ref),at.isoformat(),revision_reason]),build)
        return [o for o in self.ledger.history(as_of=self.ledger.now(),kind='Outcome') if o.research_run_ref==run_ref]
