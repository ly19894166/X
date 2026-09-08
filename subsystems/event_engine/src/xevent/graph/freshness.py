"""只针对Phase6研究链的当前知识检查；所有输入先按as_of过滤。"""
from ..ontology.contracts import ImpactVariable, IndustryResolution, IndustryImpactCandidate
from ..registry.engine import key, latest
from ..contracts import EventVersion
from ..registry.contracts import Company, SecurityVersion, CompanySecurityRelation, ResearchUniverseSnapshot
from ..exposures.contracts import CompanyExposure
from ..states.contracts import EventStateSnapshot
from ..ledger.contracts import OriginClusterVersion


def context(obj):
    if isinstance(obj,IndustryResolution):
        return obj.impact_ref.object_id,obj.ontology_ref.object_id
    if isinstance(obj,IndustryImpactCandidate):
        return obj.impact_ref.object_id,obj.ontology_ref.object_id,obj.rule_ref.object_id if obj.rule_ref else None
    return obj.object_id


class ResearchKnowledge:
    def __init__(self,view):
        self.view=view
        self.current={}
        for cls in (ImpactVariable,IndustryResolution,IndustryImpactCandidate):
            by_context={}
            for obj in latest(view,cls).values():
                k=context(obj)
                rank=(getattr(obj,'as_of',obj.available_at),obj.available_at,obj.version,obj.object_id)
                if k not in by_context or rank>by_context[k][0]: by_context[k]=(rank,obj)
            self.current[cls]={k:v[1] for k,v in by_context.items()}

    def stale(self,obj):
        return key(self.current[type(obj)][context(obj)])!=key(obj)

    def reasons(self,resolution):
        reasons=set()
        if self.stale(resolution): reasons.add('RESOLUTION_RECOMPUTE_REQUIRED')
        pending=[self.view[key(resolution.impact_ref)]]
        seen=set()
        while pending:
            impact=pending.pop()
            if key(impact) in seen: continue
            seen.add(key(impact))
            if self.stale(impact): reasons.add('IMPACT_RECOMPUTE_REQUIRED')
            pending.extend(self.view[key(r)] for r in impact.premise_refs if isinstance(self.view[key(r)],ImpactVariable))
        for r in resolution.candidate_refs:
            candidate=self.view[key(r)]
            if self.stale(candidate): reasons.add('CANDIDATE_RECOMPUTE_REQUIRED')
        return reasons

    def update_refs(self,resolution):
        """固定记录触发HOLD的当前知识，不能只保存一个无依据的原因字符串。"""
        objects=[resolution,*[self.view[key(r)] for r in resolution.candidate_refs]]
        pending=[self.view[key(resolution.impact_ref)]]; seen=set()
        while pending:
            obj=pending.pop()
            if key(obj) in seen: continue
            seen.add(key(obj)); objects.append(obj)
            pending.extend(self.view[key(r)] for r in obj.premise_refs if isinstance(self.view[key(r)],ImpactVariable))
        return [self.current[type(obj)][context(obj)] for obj in objects if self.stale(obj)]


def event_state(view,event_id):
    return max((s for s in view.values() if isinstance(s,EventStateSnapshot) and s.event_ref.object_id==event_id),
        key=lambda s:(s.available_at,s.object_id,s.version),default=None)


def path_reasons(view,p,h,knowledge):
    reasons=set()
    for cls,r,reason in ((EventVersion,p.event_ref,'EVENT'),(CompanyExposure,p.exposure_ref,'EXPOSURE'),
        (Company,p.company_ref,'COMPANY'),(SecurityVersion,p.security_ref,'SECURITY')):
        if key(latest(view,cls)[r.object_id])!=key(r): reasons.add(reason+'_RECOMPUTE_REQUIRED')
    current_event=latest(view,EventVersion)[p.event_ref.object_id]
    state=event_state(view,current_event.object_id)
    saved_state=view.get(key(p.state_ref)) if p.state_ref else max((view[key(r)] for r in p.input_version_refs
        if isinstance(view[key(r)],EventStateSnapshot)),key=lambda s:(s.available_at,s.object_id),default=None)
    if state and (state.event_ref.object_id!=current_event.object_id or key(state.event_ref)!=key(current_event)
                  or saved_state is None or key(saved_state)!=key(state)):
        reasons.add('EVENT_STATE_RECOMPUTE_REQUIRED')
    resolutions=[view[key(p.resolution_ref)]] if p.resolution_ref else [view[key(r)] for r in h.request.resolution_refs
        if p.candidate_ref in view[key(r)].candidate_refs]
    for resolution in resolutions: reasons.update(knowledge.reasons(resolution))
    for r in p.node_refs:
        obj=view[key(r)]
        if isinstance(obj,ImpactVariable) and knowledge.stale(obj): reasons.add('IMPACT_RECOMPUTE_REQUIRED')
    if p.candidate_ref and knowledge.stale(view[key(p.candidate_ref)]): reasons.add('CANDIDATE_RECOMPUTE_REQUIRED')
    snapshot=view[key(p.snapshot_ref or h.request.snapshot_ref)]
    relation=p.relation_ref or next((d.relation_ref for d in snapshot.decisions if key(d.security_ref)==key(p.security_ref)),None)
    if relation and key(latest(view,CompanySecurityRelation)[relation.object_id])!=key(relation):
        reasons.add('RELATION_RECOMPUTE_REQUIRED')
    current_snapshot=max((s for s in view.values() if isinstance(s,ResearchUniverseSnapshot)
        and s.universe_definition_version==snapshot.universe_definition_version),
        key=lambda s:(s.as_of,s.available_at,s.version,s.object_id))
    if key(current_snapshot)!=key(snapshot): reasons.add('SNAPSHOT_RECOMPUTE_REQUIRED')
    if any(isinstance(c,OriginClusterVersion) and c.basis=='CONFIRMED_SAME_ORIGIN' and c.available_at>p.as_of
        and set(c.member_origin_ids)&set(p.origin_group_ids) for c in view.values()): reasons.add('ORIGIN_RECOMPUTE_REQUIRED')
    if h.selection_manifest_ref:
        manifest=view[key(h.selection_manifest_ref)]
        if manifest.selection_status=='HOLD_INCOMPLETE_SELECTION': reasons.add('EXPOSURE_SELECTION_REVIEW_REQUIRED')
        companies={d.company_ref.object_id for d in snapshot.decisions if d.decision=='INCLUDED' and d.company_ref}
        candidates=[view[key(r)] for r in manifest.candidate_refs]
        matching={key(ex) for ex in latest(view,CompanyExposure).values() if ex.company_ref.object_id in companies
            and ex.exposure_type!='NARRATIVE_ASSOCIATION' and any(c.industry_ref is not None and c.industry_ref==ex.industry_ref
            and c.path_role==ex.business_role for c in candidates)}
        if matching!={key(r) for r in manifest.available_matching_exposure_refs}: reasons.add('EXPOSURE_SELECTION_RECOMPUTE_REQUIRED')
    else:
        reasons.add('EXPOSURE_SELECTION_REVIEW_REQUIRED')
    return reasons
