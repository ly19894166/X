"""只从PIT图构建输入；复用Phase6 freshness，不提供任意事实/用户偏好入口。"""
from ..ledger.store import digest, ref
from ..registry.engine import key, refs, latest, Registry
from ..contracts import EventVersion, EvidenceVersion
from ..contracts.common import TypeAdapter, UTCDateTime, VersionRef
from ..exposures.contracts import ExposureMetric
from ..exposures.engine import ExposureMaster
from ..graph.contracts import MappingHistory, ExposureSelectionManifest
from ..graph.freshness import ResearchKnowledge, path_reasons, event_state
from ..states.contracts import EventStateSnapshot
from .contracts import POLICY, PromptVersion, ModelConfig, ResearchPacket
from .provider import DEFAULT_PROMPTS


def vr(obj):
    return VersionRef(**ref(obj))


class ResearchStore:
    def __init__(self, ledger):
        self.ledger=ledger
        self.registry=Registry(ledger)

    def save(self, kind, identity, payload, inputs=(), version=1):
        """仅研究对象的append-only入口；时间、提交与恢复复用Ledger。"""
        payload={**payload,'policy_version':POLICY}
        def write(conn, view, batch):
            previous=sorted((r for r in view.values() if r.object_id==identity),key=lambda r:r.version)
            if previous and type(previous[-1]).__name__!=kind:
                raise ValueError('RESEARCH_ID_TYPE')
            if version!=(previous[-1].version+1 if previous else 1):
                raise ValueError('RESEARCH_VERSION')
            self.ledger._put(conn,batch,kind,identity,version,payload,refs([*inputs,*previous[-1:]]))
        self.ledger._write('P7:'+identity+':'+str(version),digest([payload,refs(inputs)]),write)
        return self.ledger.get(identity,version)

    def configure(self, identity='P7_CONFIG', *, prompt_version=1, config_version=1, **changes):
        # 版本化固定模板；不得通过外部证据修改角色/权限。
        prompt=self.save('PromptVersion',identity+':PROMPT',dict(**DEFAULT_PROMPTS,as_of=self.ledger.now().isoformat(),
            provenance_zh='独立研究固定角色模板；数据无指令权'),version=prompt_version)
        model=self.save('ModelConfig',identity,dict(provider_id='mock',model_identifier='deterministic-fixture-v1',
            prompt_version_ref=ref(prompt),as_of=self.ledger.now().isoformat(),
            provenance_zh='离线Mock能力，不代表真实模型验收',**changes),[prompt],version=config_version)
        return prompt,model

    def view(self, at):
        return {key(r):r for r in self.ledger.history(as_of=at)}

    def gates(self, history, view):
        reasons=set()
        if latest(view,MappingHistory).get(history.object_id)!=history:
            reasons.add('HISTORY_RECOMPUTE_REQUIRED')
        if history.research_status!='CURRENT_KNOWN_SUBSET': reasons.add('GRAPH_HOLD')
        current_event=latest(view,EventVersion)[history.request.event_ref.object_id]
        if key(current_event)!=key(history.request.event_ref): reasons.add('EVENT_RECOMPUTE_REQUIRED')
        state=event_state(view,current_event.object_id)
        if state is None or key(state.event_ref)!=key(history.request.event_ref):
            reasons.add('EVENT_STATE_RECOMPUTE_REQUIRED')
        if state and key(state.event_ref)==key(current_event) and (state.fact_state in ('CONTRADICTED','INVALIDATED') or state.lifecycle_status=='ARCHIVED'):
            reasons.add('EVENT_FACT_REVIEW_REQUIRED')
        knowledge=ResearchKnowledge(view)
        for r in history.request.resolution_refs:
            reasons.update(knowledge.reasons(view[key(r)]))
        for r in history.path_refs:
            reasons.update(path_reasons(view,view[key(r)],history,knowledge))
        if not history.selection_manifest_ref:
            reasons.add('EXPOSURE_SELECTION_REVIEW_REQUIRED')
        elif view[key(history.selection_manifest_ref)].selection_status!='COMPLETE_KNOWN_SUBSET':
            reasons.add('EXPOSURE_SELECTION_REVIEW_REQUIRED')
        return sorted(reasons),state

    def packet(self, identity, history_ref, model_config_ref, *, as_of, version=1,
               research_mode='MOCK_FORWARD', allow_degraded=False):
        cutoff=TypeAdapter(UTCDateTime).validate_python(as_of)
        if cutoff>self.ledger.now(): raise ValueError('PACKET_PIT_FUTURE')
        view=self.view(cutoff)
        h=self.registry.input(view,history_ref,MappingHistory)
        model=self.registry.input(view,model_config_ref,ModelConfig)
        prompt=self.registry.input(view,model.prompt_version_ref,PromptVersion)
        reasons,state=self.gates(h,view)
        if reasons and not allow_degraded: raise ValueError('RESEARCH_HOLD:'+','.join(reasons))
        if state and key(state.event_ref)!=key(h.request.event_ref): state=None
        # 只允许用户请求的图及其传递输入；不扫描全库新闻、记忆、收益或用户文本。
        closure={}; pending=[h,model,prompt]
        while pending:
            obj=pending.pop()
            if key(obj) in closure: continue
            closure[key(obj)]=obj
            for r in obj.input_version_refs:
                child=view.get(key(r))
                if child is None: raise ValueError('PACKET_PIT_REFERENCE')
                pending.append(child)
        if state:
            closure[key(state)]=state
        exposure_keys={key(view[key(r)].exposure_ref) for r in h.path_refs}
        metrics=[m for m in ExposureMaster(self.ledger).metric_view(as_of=cutoff) if key(m.exposure_ref) in exposure_keys]
        closure.update({key(m):m for m in metrics})
        paths=[view[key(r)] for r in h.path_refs]
        positive=[p for p in paths if p.world=='ECONOMIC' and p.impact_direction in ('POSITIVE','MIXED')]
        negative=[p for p in paths if p.world=='ECONOMIC' and p.impact_direction in ('NEGATIVE','MIXED')]
        narrative=[p for p in paths if p.world=='NARRATIVE']
        event=view[key(h.request.event_ref)]
        evidence=[e for e in closure.values() if isinstance(e,EvidenceVersion)]
        event_evidence=[view[key(r)] for r in event.evidence_refs]
        origin=self.ledger.origin_summary(as_of=cutoff,event_id=event.object_id,evidence_refs=event.evidence_refs)
        coverage_id=identity+':COVERAGE'
        facts=[r for r in closure.values() if type(r).__name__ in ('EventVersion','EvidenceVersion','ImpactVariable',
            'CompanyExposure','DisclosureImport','Company','SecurityVersion','IndustryImpactCandidate','IndustrySegment',
            'IndustryResolution','EventStateSnapshot','ExposureMetric')]
        payload=dict(packet_id=identity,as_of=cutoff.isoformat(),event_ref=ref(event),event_state_ref=ref(state) if state else None,
            mapping_history_ref=ref(h),path_refs=refs(paths),assessment_refs=[ref(r) for r in h.assessment_refs],
            selection_manifest_ref=ref(h.selection_manifest_ref) if h.selection_manifest_ref else None,
            positive_path_refs=refs(positive),negative_path_refs=refs(negative),narrative_path_refs=refs(narrative),
            counter_path_refs=refs(negative),company_refs=refs([p.company_ref for p in paths]),security_refs=refs([p.security_ref for p in paths]),
            origin_refs=refs([r for r in closure.values() if type(r).__name__=='OriginClusterVersion']),
            metric_refs=refs(metrics),fact_object_refs=refs(facts),evidence_refs=refs(evidence),
            search_coverage_ref=dict(object_id=coverage_id,version=version),prompt_version_ref=ref(prompt),model_config_ref=ref(model),
            gate_reasons=reasons,eligibility='REVIEW_ONLY' if reasons else 'ELIGIBLE_KNOWN_SUBSET',research_mode=research_mode,
            policy_version=POLICY,provenance_zh='固定图和证据闭包；不接收用户偏好或账户资格')
        payload['packet_hash']=digest(payload)
        unknown_gaps=[]
        if state is None or state.fact_state in ('UNVERIFIED','PLAUSIBLE','PARTIALLY_CONFIRMED'):
            unknown_gaps.append('FACT_NOT_FULLY_CONFIRMED')
        if origin['independent_source_count'] is None: unknown_gaps.append('HOLD_INDEPENDENCE_UNKNOWN')
        coverage=dict(as_of=cutoff.isoformat(),event_ref=ref(event),mapping_history_ref=ref(h),
            event_evidence_count=len(event_evidence),first_hand_source_count=len({e.source_id for e in event_evidence if e.is_first_hand is True}),
            origin_count=origin['origin_count'],independent_source_count=origin['independent_source_count'],
            independence_status=origin['status'],positive_path_count=len(positive),negative_path_count=len(negative),
            narrative_path_count=len(narrative),exposure_coverage_status='HOLD_REAL_COMPANY_EXPOSURE_COVERAGE',
            critical_unknown=bool(reasons or unknown_gaps) or not positive,has_hold=True,
            gaps=sorted(set([*reasons,*unknown_gaps,'HOLD_REAL_COMPANY_EXPOSURE_COVERAGE','FIXED_PACKET_ONLY_NO_EXTERNAL_SEARCH'])),
            evidence_refs=refs(event_evidence),policy_version=POLICY,provenance_zh='来源与Origin分别统计，不按转载数量加置信度')
        def write(conn,full,batch):
            previous=[r for r in full.values() if r.object_id==identity]
            if version!=max((r.version for r in previous),default=0)+1: raise ValueError('PACKET_VERSION')
            if any(not isinstance(r,ResearchPacket) for r in previous): raise ValueError('PACKET_ID_TYPE')
            self.ledger._put(conn,batch,'SearchCoverage',coverage_id,version,coverage,refs(closure.values()))
            self.ledger._put(conn,batch,'ResearchPacket',identity,version,payload,
                [*refs(closure.values()),payload['search_coverage_ref']])
            self.ledger.fault('after_research_packet')
        self.ledger._write('P7:PACKET:'+identity+':'+str(version),digest(payload),write)
        return self.ledger.get(identity,version)

    def provider_data(self, packet):
        # 仅模型字段白名单，永不注入系统环境、用户画像或动态latest记录。
        view=self.view(packet.as_of)
        paths=[view[key(r)] for r in packet.path_refs]
        def path(p):
            return dict(ref=ref(p),company_ref=ref(p.company_ref),security_ref=ref(p.security_ref),
                candidate_ref=ref(p.candidate_ref) if p.candidate_ref else None,evidence_refs=refs(p.evidence_refs),
                mechanism_zh=p.mechanism_zh,impact_direction=p.impact_direction,mapping_state=p.mapping_state,world=p.world)
        state=view.get(key(packet.event_state_ref)) if packet.event_state_ref else None
        eligible=[p for p in paths if p.world=='ECONOMIC' and p.impact_direction in ('POSITIVE','MIXED') and p.research_status!='HOLD']
        return dict(packet= dict(packet_hash=packet.packet_hash,event_ref=ref(packet.event_ref),
            eligibility=packet.eligibility,fact_state=state.fact_state if state else 'UNVERIFIED',
            eligible_positive_paths=[path(p) for p in eligible],negative_paths=[path(view[key(r)]) for r in packet.negative_path_refs],
            counter_path_refs=refs(packet.counter_path_refs),narrative_paths=[path(view[key(r)]) for r in packet.narrative_path_refs]),
            untrusted_evidence=[dict(ref=ref(e),claim_kind=e.claim_kind,quality_status=e.quality_status,
                raw=self.ledger.raw(e.raw_object_ref).decode('utf-8',errors='replace')) for e in
                (view[key(r)] for r in packet.evidence_refs)],
            fixed_objects=[view[key(r)].model_dump(mode='json') for r in packet.fact_object_refs],
            search_coverage=self.ledger.get(packet.search_coverage_ref.object_id,packet.search_coverage_ref.version).model_dump(mode='json'))
