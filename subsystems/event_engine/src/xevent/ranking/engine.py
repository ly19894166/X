"""Append-only ranking of the entire declared PIT universe and graph scope."""
from collections import Counter
from pydantic import TypeAdapter
from ..contracts.common import UTCDateTime, VersionRef
from ..ledger.store import ref, digest
from ..registry.engine import key, refs, Registry
from ..registry.contracts import Company, SecurityVersion, CompanySecurityRelation, ResearchUniverseSnapshot
from ..graph.contracts import MappingHistory, MappingAssessment, TransmissionPath
from ..research.contracts import AnalysisRun, ResearchPacket, ModelResult
from ..research.validation import validate_decision
from ..research.packet import vr
from ..pricing.engine import PricingEngine, fixed_refs
from ..pricing.contracts import PricingAssessment, MarketReactionFeatures, NextBuyerHypothesis, MissingDimensions, AlternativeCauseSearch, NonReactionInvestigation
from ..pricing.freshness import mode_scope
from ..exposures.contracts import ExposureMetric
from .contracts import *
from .policy import classify, ordinal_dimensions, sort_key

HOLDS=('HOLD_MODEL_PROVIDER_LIVE','HOLD_MODEL_USAGE_COST_UNVERIFIED','HOLD_MARKET_DATA_PROVIDER_LIVE',
    'HOLD_PRICING_POLICY_CALIBRATION','HOLD_RANK_POLICY_CALIBRATION','HOLD_HISTORICAL_UNIVERSE_COVERAGE',
    'HOLD_REAL_COMPANY_EXPOSURE_COVERAGE','HOLD_PRE_1992_CALENDAR','HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION')


def scope(candidate):
    return (candidate.event_ref.object_id if candidate.event_ref else 'UNRESOLVED',
        candidate.security_ref.object_id,candidate.path_ref.object_id if candidate.path_ref else 'UNRESOLVED')


def newest(objects):
    return max(objects,key=lambda o:(o.available_at,o.version,o.object_id),default=None)


def metric_scope(m):
    return m.exposure_ref.object_id,m.metric_type,m.period,m.scope,m.unit,m.currency


class RankingEngine:
    def __init__(self, ledger):
        self.ledger=ledger
        self.pricing=PricingEngine(ledger)
        self.registry=Registry(ledger)

    def view(self, at):
        return {key(o):o for o in self.ledger.history(as_of=at)}

    def load(self, view, r, cls):
        return self.registry.input(view,r,cls)

    def policy(self, identity='P9_POLICY', *, version=1, ranking_mode='ENGINEERING_FIXTURE', rules=None, policy_scope='INDEPENDENT_A_SHARE_RESEARCH'):
        rules=RankRules.model_validate(rules or {})
        data=dict(policy_id=identity,policy_scope=policy_scope,rules=rules.model_dump(mode='json'),
            as_of=self.ledger.now().isoformat(),ranking_mode=ranking_mode,policy_version=POLICY,
            provenance_zh='版本化透明ordinal工程策略；未经收益校准')
        def write(conn,v,batch):
            old=newest(o for o in v.values() if o.object_id==identity)
            if old and not isinstance(old,RankPolicy): raise ValueError('RANK_POLICY_ID_TYPE')
            if version!=(old.version+1 if old else 1): raise ValueError('RANK_POLICY_APPEND_ONLY')
            self.ledger._put(conn,batch,'RankPolicy',identity,version,data,refs([old] if old else []))
        self.ledger._write('P9:POLICY:'+identity+':'+str(version),digest(data),write)
        return self.ledger.get(identity,version)

    def _policy_reasons(self, p, v, mode):
        return ['RANK_POLICY_RECOMPUTE_REQUIRED'] if any(isinstance(o,RankPolicy)
            and mode_scope(o.ranking_mode)==mode_scope(mode) and o.policy_scope==p.policy_scope
            and o.available_at>p.available_at for o in v.values()) else []

    def _history_reasons(self,h,v):
        reasons=list(self.pricing.research.gates(h,v)[0])
        if any(isinstance(o,MappingHistory) and o.request.event_ref.object_id==h.request.event_ref.object_id
            and o.available_at>h.available_at for o in v.values()): reasons.append('MAPPING_RECOMPUTE_REQUIRED')
        return sorted(set(reasons))

    def _snapshot_reasons(self,snapshot,v):
        return ['SNAPSHOT_RECOMPUTE_REQUIRED'] if any(isinstance(o,ResearchUniverseSnapshot)
            and o.universe_definition_version==snapshot.universe_definition_version
            and o.available_at>snapshot.available_at for o in v.values()) else []

    def display_policy(self,identity,*,allowed_boards=None,version=1):
        payload=dict(allowed_boards=allowed_boards,as_of=self.ledger.now().isoformat(),ranking_mode='ENGINEERING_FIXTURE',
            policy_version=POLICY,provenance_zh='账户板块资格仅展示，禁止影响研究')
        def write(conn,v,batch):
            old=newest(o for o in v.values() if o.object_id==identity)
            if old and not isinstance(old,AccountDisplayPolicy): raise ValueError('DISPLAY_POLICY_ID_TYPE')
            if version!=(old.version+1 if old else 1): raise ValueError('DISPLAY_POLICY_VERSION')
            self.ledger._put(conn,batch,'AccountDisplayPolicy',identity,version,payload,refs([old] if old else []))
        self.ledger._write('P9:DISPLAY_POLICY:'+identity+':'+str(version),digest(payload),write)
        return self.ledger.get(identity,version)

    def execution(self,identity,security_ref,account_policy_ref,*,as_of,version=1):
        at=TypeAdapter(UTCDateTime).validate_python(as_of)
        def write(conn,view,batch):
            if at>self.ledger.now(): raise ValueError('DISPLAY_PIT')
            v={k:o for k,o in view.items() if o.available_at<=at}
            sec=self.load(v,security_ref,SecurityVersion); policy=self.load(v,account_policy_ref,AccountDisplayPolicy)
            eligibility='UNKNOWN' if policy.allowed_boards is None else 'ELIGIBLE' if sec.board in policy.allowed_boards else 'INELIGIBLE'
            codes=['ACCOUNT_BOARD_DISPLAY_ONLY']
            if sec.listing_status!='LISTED' or sec.suspension_status=='SUSPENDED': eligibility='INELIGIBLE'; codes.append('SECURITY_STATUS_DISPLAY_ONLY')
            old=newest(o for o in view.values() if o.object_id==identity)
            if old and not isinstance(old,ExecutionEligibility): raise ValueError('EXECUTION_ID_TYPE')
            if version!=(old.version+1 if old else 1): raise ValueError('EXECUTION_VERSION')
            data=dict(as_of=at.isoformat(),ranking_mode=policy.ranking_mode,policy_version=POLICY,provenance_zh='仅供执行资格展示；研究排序已冻结',
                security_ref=ref(sec),account_policy_ref=ref(policy),eligibility=eligibility,market=sec.exchange,board=sec.board,
                security_status=sec.listing_status,execution_reason_codes=codes)
            self.ledger._put(conn,batch,'ExecutionEligibility',identity,version,data,refs([sec,policy,*([old] if old else [])]))
        self.ledger._write('P9:EXECUTION:'+identity+':'+str(version),digest([ref(security_ref),ref(account_policy_ref),at.isoformat()]),write)
        return self.ledger.get(identity,version)

    def _pricing_reasons(self,a,v,at):
        reasons=self.pricing.current(vr(a),as_of=at,pricing_mode=a.pricing_mode)['recompute_reasons']
        if any(isinstance(o,PricingAssessment) and mode_scope(o.pricing_mode)==mode_scope(a.pricing_mode)
            and (o.event_ref.object_id,o.security_ref.object_id,o.request.path_ref.object_id)==
                (a.event_ref.object_id,a.security_ref.object_id,a.request.path_ref.object_id)
            and o.available_at>a.available_at for o in v.values()): reasons.append('PRICING_ASSESSMENT_RECOMPUTE_REQUIRED')
        return sorted(set(reasons))

    def build(self, identity, request, version=1):
        request=RankRequest.model_validate(request)
        # Canonicalize input order; membership is a set, never a tie-break input.
        request=request.model_copy(update={'history_refs':tuple(sorted(request.history_refs,key=key))})
        with self.ledger.lock:
            return self._build(identity,request,version)

    def _build(self,identity,request,version):
        def write(conn,all_view,batch):
            at=request.as_of
            if at>self.ledger.now(): raise ValueError('RANK_PIT_FUTURE')
            v={k:o for k,o in all_view.items() if o.available_at<=at}
            old=newest(o for o in all_view.values() if o.object_id==identity)
            if old and not isinstance(old,OpportunityPackage): raise ValueError('RANK_ID_TYPE')
            if version!=(old.version+1 if old else 1): raise ValueError('RANK_APPEND_ONLY')
            deps={}
            def take(r,cls):
                obj=self.load(v,r,cls); deps[key(obj)]=obj; return obj
            snapshot=take(request.snapshot_ref,ResearchUniverseSnapshot)
            policy=take(request.policy_ref,RankPolicy); rules=policy.rules
            if mode_scope(policy.ranking_mode)!=mode_scope(request.ranking_mode): raise ValueError('RANK_POLICY_MODE')
            histories=[take(r,MappingHistory) for r in request.history_refs]
            previous=take(request.previous_package_ref,OpportunityPackage) if request.previous_package_ref else None
            if previous and previous.ranking_mode!=request.ranking_mode: raise ValueError('RANK_PREVIOUS_SCOPE')
            if old and (not previous or vr(previous)!=vr(old)): raise ValueError('RANK_PREVIOUS_VERSION_REQUIRED')
            global_hard=[*self._policy_reasons(policy,v,request.ranking_mode),*self._snapshot_reasons(snapshot,v)]
            if request.ranking_mode=='REAL_FORWARD': global_hard.append('HOLD_REAL_FORWARD_QUALIFICATION')
            common=dict(as_of=at.isoformat(),ranking_mode=request.ranking_mode,policy_version=policy.policy_version,
                provenance_zh='固定PIT图研究与定价的离线确定性分级；评论不是新增FACT')
            staged=[]
            def stage(cls,suffix,data,inputs=()):
                oid=identity+suffix
                staged.append((cls,oid,{**common,**data},tuple(inputs)))
                return VersionRef(object_id=oid,version=version)
            rows=[]; seen=set(); samples={d.security_ref.object_id:[] for d in snapshot.decisions}
            decisions={d.security_ref.object_id:d for d in snapshot.decisions}
            for h in histories:
                hreason=self._history_reasons(h,v)
                for r in h.path_refs:
                    p=take(r,TransmissionPath)
                    d=decisions.get(p.security_ref.object_id)
                    rows.append((p.security_ref,p,h,d,hreason))
            represented={r[0].object_id for r in rows}
            for d in snapshot.decisions:
                if d.security_ref.object_id not in represented: rows.append((d.security_ref,None,None,d,[]))
            candidates=[]; vectors={}; candidate_data={}; execution_refs={}
            for sr,p,h,decision,hreason in sorted(rows,key=lambda row:(row[0].object_id,row[1].object_id if row[1] else '',row[2].object_id if row[2] else '')):
                security=take(sr,SecurityVersion)
                company=take(p.company_ref if p else decision.company_ref,Company) if p or decision.company_ref else None
                sid=(p.event_ref.object_id if p else 'UNRESOLVED',sr.object_id,p.object_id if p else 'UNRESOLVED')
                token=digest([*sid,h.object_id if h else None])[:24]
                suffix=':C:'+token
                hard=[*global_hard,*hreason]; reject=[]; soft=[]; unknown=[]
                if sid in seen: reject.append('DUPLICATE_SCOPE')
                seen.add(sid)
                if not decision or decision.decision!='INCLUDED' or decision.security_ref!=sr or company is None:
                    reject.append('INVALID_IDENTITY')
                if decision and company and decision.company_ref!=vr(company): reject.append('INVALID_IDENTITY')
                if p:
                    relation=take(p.relation_ref,CompanySecurityRelation) if p.relation_ref else None
                    if (not relation or relation.security_ref!=sr or relation.company_ref!=p.company_ref
                        or security.company_ref!=p.company_ref): reject.append('INVALID_IDENTITY')
                    if p.snapshot_ref!=request.snapshot_ref: hard.append('SNAPSHOT_RECOMPUTE_REQUIRED')
                    if p.research_status=='HOLD': hard.append('INVALID_PATH')
                    if p.mapping_state in ('INVALID','CONTRADICTED'): reject.append('INVALID_PATH')
                    if p.world=='ECONOMIC' and p.impact_direction not in ('POSITIVE','MIXED'): reject.append('UNSUPPORTED_BENEFICIARY')
                    if p.research_status=='DEGRADED': soft.append('PATH_DEGRADED')
                else: hard.append('NO_KNOWN_PATH'); unknown.append('COMPANY_EXPOSURE_OR_EVENT_MAPPING_NOT_COVERED')
                dim=RankDimensions(world=p.world if p else 'ECONOMIC',exposure_type=p.exposure_type if p else 'UNKNOWN')
                runs=[o for o in v.values() if isinstance(o,AnalysisRun)
                    and o.research_mode==('HISTORICAL_REPLAY' if request.ranking_mode=='HISTORICAL_REPLAY' else 'MOCK_FORWARD')
                    and p and self.pricing._analysis_scope(v,o,sr.object_id)==(p.event_ref.object_id,sr.object_id,o.research_mode)]
                analysis=newest(runs)
                if analysis: deps[key(analysis)]=analysis
                primary=red=adj=packet=selected=pricing=None
                countercase=[]; failures=[]; counter_refs=[]; support=[]; metrics=[]
                positives=[]; negatives=[]; missing=[]
                if h:
                    for ar in h.assessment_refs:
                        ma=take(ar,MappingAssessment)
                        if company and ma.company_ref.object_id==company.object_id:
                            positives.extend(ma.positive_path_refs); negatives.extend(ma.negative_path_refs); counter_refs.extend(ma.counter_path_refs)
                if analysis:
                    packet=take(analysis.packet_ref,ResearchPacket)
                    primary=take(analysis.primary_result_ref,ModelResult) if analysis.primary_result_ref else None
                    red=take(analysis.red_team_ref,ModelResult) if analysis.red_team_ref else None
                    adj=take(analysis.adjudication_ref,ModelResult) if analysis.adjudication_ref else None
                    validate_decision(analysis,primary,red,adj)
                    if primary:
                        hs=primary.primary
                        selected=next((x for x in (hs.target,*hs.alternatives,hs.null_hypothesis) if x.hypothesis_id==analysis.final_hypothesis_id),None)
                    dim=dim.model_copy(update=dict(research_status=analysis.analysis_status,decision_source=analysis.decision_source,
                        final_choice=analysis.final_choice,red_team_status=red.red_team.verdict if red else 'INCOMPLETE'))
                    if analysis.analysis_status=='HOLD': hard.append('RESEARCH_HOLD')
                    elif analysis.final_choice=='NULL' and p.world=='ECONOMIC': reject.append('RESEARCH_NULL')
                    if red:
                        countercase=list(red.red_team.challenges_zh); failures.extend(red.red_team.failure_conditions_zh)
                        counter_refs.extend(red.red_team.evidence_refs); counter_refs.extend(red.red_team.counter_path_refs)
                        if red.red_team.verdict in ('TARGET_INVALIDATED','NULL_PREFERRED') and p.world=='ECONOMIC': reject.append('RED_TEAM_INVALIDATED')
                    if selected:
                        failures.extend(selected.failure_conditions); unknown.extend(selected.unknowns); support.extend(selected.supporting_evidence_refs)
                    if p.world=='ECONOMIC' and (not selected or vr(p) not in selected.supporting_path_refs
                        or selected.security_ref!=sr or selected.company_ref!=p.company_ref or packet.mapping_history_ref!=vr(h)):
                        hard.append('SELECTED_ECONOMIC_PATH_REQUIRED')
                    if packet.mapping_history_ref!=vr(h): hard.append('ANALYSIS_RECOMPUTE_REQUIRED')
                else: hard.append('RESEARCH_HOLD')
                if p:
                    pricing=newest(o for o in v.values() if isinstance(o,PricingAssessment)
                        and mode_scope(o.pricing_mode)==mode_scope(request.ranking_mode)
                        and o.request.path_ref==vr(p) and o.security_ref==sr and o.event_ref==p.event_ref)
                if pricing:
                    deps[key(pricing)]=pricing
                    if not analysis or pricing.request.analysis_ref!=vr(analysis): hard.append('PRICING_ASSESSMENT_RECOMPUTE_REQUIRED')
                    hard.extend(self._pricing_reasons(pricing,v,at))
                    mi=take(pricing.missing_dimensions_ref,MissingDimensions)
                    missing=[m.dimension for m in mi.items]
                    if any(m.severity=='BLOCKING' for m in mi.items): hard.append('BLOCKING_MISSING_DATA')
                    soft.extend(m.dimension for m in mi.items if m.severity=='DEGRADED')
                    cause=take(pricing.alternative_cause_ref,AlternativeCauseSearch)
                    nr=take(pricing.non_reaction_ref,NonReactionInvestigation)
                    feat=take(pricing.features_ref,MarketReactionFeatures)
                    buyers=[take(r,NextBuyerHypothesis) for r in pricing.next_buyer_refs]
                    buyers=[b for b in buyers if b.supporting_path_refs and all(r==vr(p) for r in b.supporting_path_refs)]
                    bstatus=next((s for s in ('SUPPORTED','PLAUSIBLE','WEAK','REJECTED') if any(b.hypothesis_status==s for b in buyers)),'UNKNOWN')
                    for b in buyers:
                        if b.failure_condition: failures.append(b.failure_condition)
                    updated={n:getattr(pricing,n) for n in ('thesis_strength','recognition_state','price_in_band','crowding_band','remaining_edge','reversal_risk')}
                    dim=dim.model_copy(update={**updated,'pricing_status':pricing.assessment_status,'next_buyer_status':bstatus,
                        'alternative_cause_status':cause.cause_status,'nonreaction_status':nr.investigation_status})
                    if pricing.assessment_status=='HOLD': hard.append('PRICING_HOLD')
                    if (feat.diffusion and feat.diffusion.coverage=='COMPLETE_DECLARED_SCOPE'
                        and feat.diffusion.breadth_ratio is not None and feat.diffusion.breadth_ratio>=rules.broad_diffusion
                        and feat.industry_relative_return is not None and abs(feat.industry_relative_return)<=rules.beta_max_relative
                        and cause.cause_status=='MULTI_CAUSE'):
                        dim=dim.model_copy(update={'systemic_basis':'BROAD_SECTOR_RELATIVE_NEUTRAL'})
                else: hard.append('PRICING_HOLD')
                if p and packet:
                    # Only verified revenue-share facts already in the fixed research packet.
                    ms=[take(r,ExposureMetric) for r in packet.metric_refs]
                    ms=[m for m in ms if m.exposure_ref==p.exposure_ref and m.metric_type=='REVENUE_SHARE'
                        and m.validation_status=='VERIFIED' and m.result_status=='DEFINED']
                    if len(ms)==1:
                        metrics=[vr(ms[0])]
                        dim=dim.model_copy(update={'purity':'HIGH' if ms[0].value>=rules.high_revenue_share else 'LOW'})
                        if any(isinstance(o,ExposureMetric) and metric_scope(o)==metric_scope(ms[0])
                            and o.available_at>ms[0].available_at for o in v.values()): hard.append('METRIC_RECOMPUTE_REQUIRED')
                if dim.purity=='UNKNOWN': soft.append('PURITY_UNKNOWN_NO_INVENTED_SHARE')
                if soft: dim=dim.model_copy(update={'missingness':'SOFT_MISSING'})
                # Narrative pricing cannot rescue economics; keep observation-only rows in their own list.
                grade,state,codes=classify(dim,rules,hard=hard,reject=reject,countercase=countercase,failures=failures,soft=soft)
                if dim.world=='NARRATIVE' and not reject:
                    codes=tuple(sorted(set((*codes,'NARRATIVE_ONLY_FOR_ECONOMIC_ALPHA'))))
                vector=dict(candidate_grade=grade,processing_state=state,dimensions=[x.model_dump(mode='json') for x in ordinal_dimensions(dim,rules)],
                    tie_break=sid,policy_ref=ref(policy))
                vref=stage(RankVector,suffix+':VECTOR',vector)
                if sr not in execution_refs:
                    execution_refs[sr]=stage(ExecutionEligibility,':EXEC:'+digest(ref(sr))[:20],dict(security_ref=ref(sr),eligibility='UNKNOWN',
                        market=security.exchange,board=security.board,security_status=security.listing_status,
                        execution_reason_codes=['ACCOUNT_POLICY_NOT_PROVIDED']))
                rrefs=[]
                if state in ('REJECT','HOLD'):
                    category=next((c for c in codes if c in ('INVALID_IDENTITY','INVALID_PATH','RESEARCH_NULL','RESEARCH_HOLD',
                        'RED_TEAM_INVALIDATED','PRICING_HOLD','BLOCKING_MISSING_DATA','DUPLICATE_SCOPE','UNSUPPORTED_BENEFICIARY','PIT_INVALID')),'OTHER_EXPLICIT')
                    rrefs=[stage(RejectReason,suffix+':REASON',dict(category=category,detail_codes=codes,explanation_zh='本样本保留，具体阻塞或拒绝原因见机器码'))]
                data=dict(**dim.model_dump(mode='json'),candidate_id=identity+suffix,event_ref=ref(p.event_ref) if p else None,
                    security_ref=ref(sr),company_ref=ref(company) if company else None,path_ref=ref(p) if p else None,
                    history_ref=ref(h) if h else None,analysis_ref=ref(analysis) if analysis else None,
                    pricing_assessment_ref=ref(pricing) if pricing else None,candidate_grade=grade,processing_state=state,
                    mapping_state=p.mapping_state if p else 'UNRESOLVED',positive_path_refs=refs(positives),negative_path_refs=refs(negatives),
                    counter_refs=refs(counter_refs),supporting_evidence_refs=refs(support),metric_refs=refs(metrics),
                    countercase=countercase,failure_conditions=sorted(set(failures)),unknowns=sorted(set(unknown+soft)),missing_dimensions=missing,
                    rank_vector_ref=ref(vref),execution_eligibility_ref=ref(execution_refs[sr]),reject_reason_refs=refs(rrefs),
                    candidate_reason_codes=codes,grade_reason_zh='工程分级 '+grade+'；依据：'+'，'.join(codes))
                cref=stage(CandidateVersion,suffix,data,[vref,execution_refs[sr],*rrefs])
                candidates.append(cref); candidate_data[cref]=data; vectors[cref]=vector
                if sr.object_id in samples: samples[sr.object_id].append(cref)
            from types import SimpleNamespace
            def ordering(r):
                d=vectors[r]
                return sort_key(SimpleNamespace(**{**d,'dimensions':tuple(OrdinalDimension.model_validate(x) for x in d['dimensions'])}),rules)
            ordered=sorted(candidates,key=ordering)
            # Rank positions are world-specific. HOLD and REJECT stay in the manifest but have no rank.
            entries=[]; worlds={world:[] for world in ('ECONOMIC','NARRATIVE')}
            for r in ordered:
                d=candidate_data[r]
                if d['processing_state']=='REJECT' or (d['processing_state']=='HOLD' and d['world']=='ECONOMIC'): continue
                worlds[d['world']].append(r)
                entries.append(dict(candidate_ref=ref(r),rank=len(worlds[d['world']]),grade=d['candidate_grade'],world=d['world']))
            summaries=[]
            for world in worlds:
                for sec in sorted({candidate_data[r]['security_ref']['object_id'] for r in candidates if candidate_data[r]['world']==world}):
                    members=[r for r in ordered if candidate_data[r]['security_ref']['object_id']==sec and candidate_data[r]['world']==world]
                    paths=[VersionRef.model_validate(candidate_data[r]['path_ref']) for r in members if candidate_data[r]['path_ref']]
                    winner=next((candidate_data[r]['path_ref'] for r in members if r in worlds[world]),None)
                    summaries.append(dict(security_ref=candidate_data[members[0]]['security_ref'],world=world,winner_path_ref=winner,
                        all_candidate_path_refs=refs(paths),positive_path_refs=refs(VersionRef.model_validate(x) for r in members for x in candidate_data[r]['positive_path_refs']),
                        negative_path_refs=refs(VersionRef.model_validate(x) for r in members for x in candidate_data[r]['negative_path_refs'])))
            rankref=stage(RankSnapshot,':RANK',dict(entries=entries,economic_ranking=[ref(r) for r in worlds['ECONOMIC']],
                narrative_ranking=[ref(r) for r in worlds['NARRATIVE']],economic_alpha_refs=[e['candidate_ref'] for e in entries if e['world']=='ECONOMIC' and e['grade'] in ('ALPHA1','ALPHA2')],
                beta_refs=[e['candidate_ref'] for e in entries if e['grade']=='BETA'],security_summaries=summaries,policy_ref=ref(policy)),candidates)
            counts=Counter(candidate_data[r]['candidate_grade'] for r in candidates)
            manifest=stage(RankManifest,':MANIFEST',dict(snapshot_ref=ref(snapshot),history_refs=refs(histories),candidate_refs=refs(candidates),
                outside_universe_candidate_refs=[ref(r) for r in candidates if candidate_data[r]['security_ref']['object_id'] not in decisions],
                samples=[dict(security_ref=ref(d.security_ref),universe_decision=d.decision,candidate_refs=refs(samples[d.security_ref.object_id]),
                    reason_codes=list(d.reason_codes)) for d in snapshot.decisions],universe_total=len(snapshot.decisions),total=len(candidates),
                eligible_for_ranking=counts['ALPHA1']+counts['ALPHA2']+counts['BETA'],
                hold=sum(candidate_data[r]['processing_state']=='HOLD' for r in candidates),**{g.lower():counts[g] for g in ('ALPHA1','ALPHA2','BETA','WATCH','OVERPRICED','REJECT')}),candidates)
            changes=[]
            prev_by_scope={}; prev_ranks={}
            if previous:
                previous_rank=take(previous.rank_snapshot_ref,RankSnapshot)
                prev_ranks={e.candidate_ref:e.rank for e in previous_rank.entries}
                for r in previous.candidate_refs:
                    c=take(r,CandidateVersion); prev_by_scope[scope(c)]=c
            current_ranks={VersionRef.model_validate(e['candidate_ref']):e['rank'] for e in entries}
            for r in candidates:
                d=candidate_data[r]; sid=tuple(vectors[r]['tie_break']); prev=prev_by_scope.pop(sid,None)
                before=prev.candidate_grade if prev else None; after=d['candidate_grade']
                change='NEW' if prev is None else 'UNCHANGED' if before==after else 'REJECTED' if after=='REJECT' else 'OVERPRICED' if after=='OVERPRICED' else 'UPGRADED' if RankRules.model_fields['grade_order'].default.index(after)<RankRules.model_fields['grade_order'].default.index(before) else 'DOWNGRADED'
                changed=[n for n in RankDimensions.model_fields if prev and getattr(prev,n)!=d[n]]
                pr=prev_ranks.get(vr(prev)) if prev else None; cr=current_ranks.get(r)
                changes.append(stage(CandidateChange,':CHANGE:'+digest(ref(r))[:20],dict(previous_candidate_ref=ref(prev) if prev else None,current_candidate_ref=ref(r),
                    from_grade=before,to_grade=after,grade_change=change,previous_rank=pr,current_rank=cr,
                    rank_change=cr-pr if cr is not None and pr is not None else None,changed_dimensions=changed,change_reason_codes=d['candidate_reason_codes']),[r,*([prev] if prev else [])]))
            for prev in prev_by_scope.values():
                changes.append(stage(CandidateChange,':REMOVED:'+digest(ref(prev))[:20],dict(previous_candidate_ref=ref(prev),current_candidate_ref=None,
                    from_grade=prev.candidate_grade,to_grade=None,grade_change='REMOVED',previous_rank=prev_ranks.get(vr(prev)),current_rank=None,
                    rank_change=None,changed_dimensions=['DECLARED_SCOPE'],change_reason_codes=['NOT_IN_CURRENT_DECLARED_SCOPE']),[prev]))
            outputs=[]
            for cls,oid,data,inputs in staged:
                self.ledger._put(conn,batch,cls.__name__,oid,version,data,refs([*deps.values(),*inputs,*fixed_refs(data)]))
                outputs.append(VersionRef(object_id=oid,version=version))
            self.ledger._put(conn,batch,'OpportunityPackage',identity,version,{**common,'request':request.model_dump(mode='json'),
                'candidate_refs':refs(candidates),'rank_snapshot_ref':ref(rankref),'manifest_ref':ref(manifest),'change_refs':refs(changes),
                'empty_opportunity_list':not any(candidate_data[r]['candidate_grade'] in ('ALPHA1','ALPHA2','BETA') for r in candidates),
                'hold_reasons':sorted(set((*HOLDS,*global_hard)))},refs([*deps.values(),*outputs,*([old] if old else [])]))
            self.ledger.fault('after_rank_package')
        self.ledger._write('P9:BUILD:'+identity+':'+str(version),digest(request.model_dump(mode='json')),write)
        return self.ledger.get(identity,version)

    def current(self,package_ref,*,as_of,ranking_mode):
        at=TypeAdapter(UTCDateTime).validate_python(as_of); v=self.view(at)
        package=self.load(v,package_ref,OpportunityPackage)
        if package.ranking_mode!=ranking_mode: raise ValueError('RANK_MODE_ISOLATION')
        policy=self.load(v,package.request.policy_ref,RankPolicy)
        reasons=self._policy_reasons(policy,v,ranking_mode)
        for hr in package.request.history_refs:
            reasons.extend(self._history_reasons(self.load(v,hr,MappingHistory),v))
        for cr in package.candidate_refs:
            c=self.load(v,cr,CandidateVersion)
            for mr in c.metric_refs:
                metric=v[key(mr)]
                if any(isinstance(o,ExposureMetric) and metric_scope(o)==metric_scope(metric)
                    and o.available_at>metric.available_at for o in v.values()): reasons.append('METRIC_RECOMPUTE_REQUIRED')
            if c.pricing_assessment_ref: reasons.extend(self._pricing_reasons(self.load(v,c.pricing_assessment_ref,PricingAssessment),v,at))
            if c.analysis_ref:
                a=v[key(c.analysis_ref)]
                if any(isinstance(o,AnalysisRun) and self.pricing._analysis_scope(v,o,c.security_ref.object_id)==self.pricing._analysis_scope(v,a,c.security_ref.object_id)
                    and o.available_at>a.available_at for o in v.values()): reasons.append('ANALYSIS_RECOMPUTE_REQUIRED')
            elif c.event_ref and any(isinstance(o,AnalysisRun)
                and o.research_mode==('HISTORICAL_REPLAY' if ranking_mode=='HISTORICAL_REPLAY' else 'MOCK_FORWARD')
                and self.pricing._analysis_scope(v,o,c.security_ref.object_id)==(c.event_ref.object_id,c.security_ref.object_id,o.research_mode)
                and o.available_at>package.available_at for o in v.values()): reasons.append('ANALYSIS_RECOMPUTE_REQUIRED')
            # Previously unpriced candidates must also notice their first pricing result.
            if c.path_ref and any(isinstance(o,PricingAssessment) and mode_scope(o.pricing_mode)==mode_scope(ranking_mode)
                and o.request.path_ref==c.path_ref and o.available_at>package.available_at for o in v.values()): reasons.append('PRICING_ASSESSMENT_RECOMPUTE_REQUIRED')
        snapshot=v[key(package.request.snapshot_ref)]
        reasons.extend(self._snapshot_reasons(snapshot,v))
        if reasons: reasons.append('RANK_RECOMPUTE_REQUIRED')
        return dict(package=package,freshness='RECOMPUTE_REQUIRED' if reasons else 'AS_RECORDED',
            current_status='HOLD' if reasons else 'ENGINEERING_ONLY',recompute_reasons=sorted(set(reasons)),formal_live_alpha=False)

    def report(self,package_ref,*,as_of,ranking_mode,execution_refs=()):
        state=self.current(package_ref,as_of=as_of,ranking_mode=ranking_mode); package=state['package']; v=self.view(as_of)
        rank=v[key(package.rank_snapshot_ref)]; manifest=v[key(package.manifest_ref)]
        positions={e.candidate_ref:e.rank for e in rank.entries}
        display={}
        for er in execution_refs:
            execution=self.load(v,er,ExecutionEligibility)
            if execution.security_ref in display: raise ValueError('DISPLAY_DUPLICATE_SECURITY')
            display[execution.security_ref]=execution
        def item(r):
            c=v[key(r)]; s=v[key(c.security_ref)]; co=v[key(c.company_ref)] if c.company_ref else None
            return dict(排名=positions.get(r),等级=c.candidate_grade,处理状态=c.processing_state,公司=co.canonical_name_zh if co else 'UNKNOWN',
                证券=s.security_name,证券代码=s.security_code,事件=c.event_ref.model_dump() if c.event_ref else None,
                经济路径=c.path_ref.model_dump() if c.path_ref else None,假设=c.final_choice,主要支持=refs(c.supporting_evidence_refs),
                主要反证=list(c.countercase),反路径=refs(c.negative_path_refs),Price_in=c.price_in_band,Remaining_Edge=c.remaining_edge,
                Next_Buyer=c.next_buyer_status,Reversal_Risk=c.reversal_risk,Alternative_Cause=c.alternative_cause_status,
                UNKNOWN=list(c.unknowns),失效条件=list(c.failure_conditions),原因=list(c.candidate_reason_codes),
                执行资格=display.get(c.security_ref,v[key(c.execution_eligibility_ref)]).eligibility)
        # As-recorded always remains auditable; stale lists cannot be presented as current.
        return dict(声明=['ENGINEERING_DEMO','NO_ALPHA_CLAIM','NO_INVESTMENT_ADVICE'],资格='ENGINEERING_ONLY',
            正式Alpha=False,模式=package.ranking_mode,输入截止=package.as_of.isoformat(),结果可用=package.available_at.isoformat(),
            当前状态=state['current_status'],重算原因=state['recompute_reasons'],研究范围=manifest.snapshot_ref.model_dump(),
            样本统计={n:getattr(manifest,n) for n in ('universe_total','total','eligible_for_ranking','alpha1','alpha2','beta','watch','overpriced','reject','hold')},
            空榜=package.empty_opportunity_list,当前经济榜=[] if state['recompute_reasons'] else [item(r) for r in rank.economic_ranking],
            当前叙事榜=[] if state['recompute_reasons'] else [item(r) for r in rank.narrative_ranking],
            已记录全样本=[item(r) for r in package.candidate_refs],HOLD=list(package.hold_reasons))
