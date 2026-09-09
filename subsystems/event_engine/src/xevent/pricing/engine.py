"""PIT市场输入及定价发布；复用既有Ledger，不联网、不改上游研究。"""
from datetime import timedelta, timezone
from pydantic import TypeAdapter
from ..contracts import Source, EvidenceVersion, EventVersion
from ..contracts.common import UTCDateTime, VersionRef, InputVersionRef
from ..ledger.store import ref, digest
from ..ledger.contracts import NoveltyDecision
from ..registry.engine import Registry, key, refs, latest
from ..registry.contracts import SecurityVersion
from ..ontology.contracts import IndustrySegment
from ..graph.contracts import TransmissionPath, MappingHistory, MappingAssessment
from ..exposures.contracts import CompanyExposure
from ..research.contracts import AnalysisRun, ResearchPacket, ModelResult
from ..research.packet import ResearchStore, vr
from ..research.validation import validate_decision
from ..research.engine import HOLDS
from .contracts import *
from .calculations import price_return, comparable, quality, observation_key, volume_multiple, diffusion, classify_dimensions

INPUTS=(MarketInstrument,MarketSession,AdjustmentBasis,ProviderQualification,MarketObservation,
        BenchmarkComposition,PricingContext,PricingPolicy)
ENVELOPE_FIELDS={'object_id','version','recorded_at','available_at','computed_at','input_version_refs',
                'run_id','content_hash','policy_version','schema_version','mode','public_pit','research_computed_at'}


def fixed_refs(data):
    """只收集已由Pydantic定义的固定版本引用，不解释自由文本。"""
    found=[]
    if isinstance(data,dict):
        if set(data)=={'object_id','version'}: found.append(VersionRef.model_validate(data))
        else:
            for v in data.values(): found.extend(fixed_refs(v))
    elif isinstance(data,(list,tuple)):
        for v in data: found.extend(fixed_refs(v))
    return tuple(sorted(set(found),key=key))


def event_anchor(event):
    return EventAnchor(event_ref=vr(event),public_time=event.first_public_at,first_seen_time=event.first_seen_at,
        known_at=max(event.available_at,event.first_seen_at,event.first_public_at or event.first_seen_at),
        proof_refs=event.evidence_refs)


def validate_reaction_window(anchor,window,as_of):
    if window.start<anchor.known_at or window.end>as_of:
        raise ValueError('EVENT_ANCHOR_WINDOW：事件后窗口不得早于系统合法可知时点或超过as_of')


class PricingEngine:
    def __init__(self,ledger):
        self.ledger=ledger
        self.registry=Registry(ledger)
        self.research=ResearchStore(ledger)

    def view(self,at):
        return {key(o):o for o in self.ledger.history(as_of=at)}

    def load(self,view,r,cls=PricingEnvelope):
        return self.registry.input(view,r,cls)

    def _analysis_scope(self,view,analysis,security_id):
        packet=view.get(key(analysis.packet_ref))
        return (packet.event_ref.object_id if packet else None,
                security_id if packet and any(r.object_id==security_id for r in packet.security_refs) else None,
                analysis.research_mode)

    def _put(self,conn,view,batch,cls,identity,version,payload,dependencies):
        previous=sorted((o for o in view.values() if o.object_id==identity),key=lambda o:o.version)
        if previous and type(previous[-1]) is not cls: raise ValueError('PRICING_ID_TYPE')
        if version!=(previous[-1].version+1 if previous else 1): raise ValueError('PRICING_APPEND_ONLY')
        self.ledger._put(conn,batch,cls.__name__,identity,version,{**payload,'policy_version':POLICY},
            refs([*dependencies,*previous[-1:],*fixed_refs(payload)]))

    def publish(self,cls,identity,payload,*,as_of,version=1,pricing_mode='ENGINEERING_FIXTURE'):
        """只允许显式结构化输入；不是网络或ChatGPT导入Bridge。"""
        if cls not in INPUTS: raise ValueError('PRICING_INPUT_KIND')
        cutoff=TypeAdapter(UTCDateTime).validate_python(as_of)
        if set(payload)&ENVELOPE_FIELDS: raise ValueError('PRICING_ENVELOPE_RESERVED')
        data={**payload,'as_of':cutoff.isoformat(),'pricing_mode':pricing_mode}
        def write(conn,view,batch):
            if cutoff>self.ledger.now(): raise ValueError('PRICING_PIT_FUTURE')
            v={k:o for k,o in view.items() if o.available_at<=cutoff}
            dependencies=[self.load(v,r,(PricingEnvelope,Source,EvidenceVersion,SecurityVersion,IndustrySegment,EventVersion)) for r in fixed_refs(data)]
            now=self.ledger.now()
            obj=cls.model_validate({**data,'object_id':identity,'version':version,'recorded_at':now,'available_at':now,
                'computed_at':now,'run_id':batch,'content_hash':'0'*64,'policy_version':POLICY,
                'input_version_refs':[InputVersionRef(**ref(o),available_at=o.available_at) for o in dependencies]})
            self._input_gate(obj,v)
            self._put(conn,view,batch,cls,identity,version,data,dependencies)
        self.ledger._write('P8:INPUT:'+identity+':'+str(version),digest(data),write)
        return self.ledger.get(identity,version)

    def _quote(self,v,r,span):
        ev=self.load(v,r,EvidenceVersion)
        if ev.claim_kind!='FACT' or ev.quality_status!='VALIDATED' or not span or span not in self.ledger.raw(ev.raw_object_ref).decode('utf-8'):
            raise ValueError('PRICING_FINDING_PROVENANCE')
        return ev

    def _input_gate(self,o,v):
        if isinstance(o,(MarketSession,AdjustmentBasis,MarketObservation)):
            self.load(v,o.instrument_ref,(SecurityVersion,MarketInstrument))
        if hasattr(o,'source_ref'): self.load(v,o.source_ref,Source)
        if isinstance(o,MarketObservation):
            instrument=v[key(o.instrument_ref)]
            adjustment=self.load(v,o.adjustment_ref,AdjustmentBasis)
            session=self.load(v,o.session_ref,MarketSession)
            provider=self.load(v,o.provider_ref,ProviderQualification)
            if (adjustment.instrument_ref!=o.instrument_ref or adjustment.adjustment_type!=o.adjustment_type
                or session.instrument_ref!=o.instrument_ref or provider.source_ref!=o.source_ref or provider.provider!=o.provider):
                raise ValueError('MARKET_BINDING')
            if o.currency is not None and o.currency!=instrument.currency: raise ValueError('MARKET_CURRENCY')
            if o.observation_type in ('PRICE','VWAP','CROSS_ASSET','AMOUNT') and o.currency is None: raise ValueError('MARKET_CURRENCY')
            if o.quality_status=='QUALIFIED' and provider.qualification_status!='PROVIDER_QUALIFIED': raise ValueError('PROVIDER_HOLD')
            if o.quality_status=='QUALIFIED' and not any(w.start<=o.window.start<=o.window.end<=w.end for w in session.intervals):
                raise ValueError('MARKET_SESSION_WINDOW')
            if o.observation_type in ('RETURN','INDUSTRY_RETURN','BENCHMARK_RETURN'):
                points=[self.load(v,r,MarketObservation) for r in o.component_price_refs]
                if any(p.observation_type!='PRICE' for p in points): raise ValueError('RETURN_ENDPOINTS')
                calculated=price_return(points)
                if calculated is None or o.value is None or abs(calculated-o.value)>1e-10: raise ValueError('RETURN_ENDPOINTS')
                if points[0].window.end!=o.window.start or points[-1].window.end!=o.window.end or points[0].instrument_ref!=o.instrument_ref:
                    raise ValueError('RETURN_WINDOW')
        if isinstance(o,BenchmarkComposition):
            self.load(v,o.benchmark_ref,MarketInstrument)
            for r in o.component_security_refs: self.load(v,r,SecurityVersion)
            if o.industry_ref: self.load(v,o.industry_ref,IndustrySegment)
        if isinstance(o,PricingContext):
            self.load(v,o.event_ref,EventVersion); self.load(v,o.security_ref,SecurityVersion)
            for finding in o.findings:
                if finding.outcome!='UNKNOWN': self._quote(v,finding.evidence_ref,finding.quoted_span)

    def benchmark(self,identity,*,price_refs,composition_ref,benchmark_role,as_of,version=1,pricing_mode='ENGINEERING_FIXTURE'):
        cutoff=TypeAdapter(UTCDateTime).validate_python(as_of)
        data=dict(price_refs=[ref(r) for r in price_refs],composition_ref=ref(composition_ref),benchmark_role=benchmark_role,
                  as_of=cutoff.isoformat(),pricing_mode=pricing_mode)
        def write(conn,view,batch):
            if cutoff>self.ledger.now(): raise ValueError('PRICING_PIT_FUTURE')
            v={k:o for k,o in view.items() if o.available_at<=cutoff}
            points=[self.load(v,r,MarketObservation) for r in price_refs]
            comp=self.load(v,composition_ref,BenchmarkComposition)
            if len(points)!=2 or any(p.instrument_ref!=comp.benchmark_ref for p in points): raise ValueError('BENCHMARK_ENDPOINTS')
            if any(p.observation_type!='PRICE' for p in points): raise ValueError('BENCHMARK_PRICE')
            value=price_return(points)
            payload={**data,'benchmark_ref':ref(comp.benchmark_ref),'window':dict(start=points[0].window.end.isoformat(),end=points[1].window.end.isoformat()),
                'return_value':value,'adjustment_ref':ref(points[0].adjustment_ref),'source_ref':ref(points[0].source_ref),
                'quality_status':'QUALIFIED' if value is not None else 'HOLD','observed_at':points[1].observed_at.isoformat(),
                'provenance_zh':'固定价格端点与当时成分；简单收益不是事件因果'}
            self._put(conn,view,batch,BenchmarkSnapshot,identity,version,payload,[comp,*points])
        self.ledger._write('P8:BENCHMARK:'+identity+':'+str(version),digest(data),write)
        return self.ledger.get(identity,version)

    def assess(self,identity,request,version=1):
        request=PricingRequest.model_validate(request)
        with self.ledger.lock:
            return self._assess(identity,request,version)

    def _assess(self,identity,request,version):
        def write(conn,all_view,batch):
            at=request.as_of
            if at>self.ledger.now(): raise ValueError('PRICING_PIT_FUTURE')
            v={k:o for k,o in all_view.items() if o.available_at<=at}
            deps={}
            def take(r,cls):
                o=self.load(v,r,cls); deps[key(o)]=o; return o
            analysis=take(request.analysis_ref,AnalysisRun)
            packet=take(analysis.packet_ref,ResearchPacket)
            history=take(packet.mapping_history_ref,MappingHistory)
            event=take(packet.event_ref,EventVersion)
            security=take(request.security_ref,SecurityVersion)
            path=take(request.path_ref,TransmissionPath)
            policy=take(request.policy_ref,PricingPolicy); rules=policy.rules
            if path.path_id not in {r.object_id for r in history.path_refs} or request.path_ref not in history.path_refs or path.security_ref!=request.security_ref:
                raise ValueError('PRICING_PATH_SCOPE')
            for r in packet.assessment_refs: take(r, MappingAssessment)
            primary=take(analysis.primary_result_ref,ModelResult) if analysis.primary_result_ref else None
            red=take(analysis.red_team_ref,ModelResult) if analysis.red_team_ref else None
            adj=take(analysis.adjudication_ref,ModelResult) if analysis.adjudication_ref else None
            validate_decision(analysis,primary,red,adj)
            missing=[]; block=[]
            def miss(code,severity='DEGRADED',source='UNKNOWN'):
                if code not in {m.dimension for m in missing}:
                    missing.append(MissingItem(dimension=code,reason='该维度缺失、不可比或需要重新核验：'+code,severity=severity,
                        required_for_formal_pricing=severity=='BLOCKING',source_status=source))
                if severity=='BLOCKING': block.append(code)
            if analysis.analysis_status=='HOLD' or analysis.decision_source=='HOLD_GATE': miss('RESEARCH_HOLD','BLOCKING')
            if analysis.final_choice not in ('TARGET','ALT'): miss('RESEARCH_NULL_NO_TARGET','BLOCKING')
            selected=None
            if primary:
                hs=primary.primary
                selected=next((h for h in (hs.target,*hs.alternatives,hs.null_hypothesis) if h.hypothesis_id==analysis.final_hypothesis_id),None)
            if selected is None or request.path_ref not in selected.supporting_path_refs: miss('SELECTED_ECONOMIC_PATH_REQUIRED','BLOCKING')
            if path.world!='ECONOMIC' or path.research_status=='HOLD': miss('ECONOMIC_PATH_HOLD','BLOCKING')
            if request.pricing_mode=='REAL_FORWARD': miss('HOLD_MODEL_PROVIDER_LIVE','BLOCKING')
            if analysis.research_mode=='HISTORICAL_REPLAY' and request.pricing_mode!='HISTORICAL_REPLAY': miss('RESEARCH_MODE_MISMATCH','BLOCKING')
            gates,_=self.research.gates(history,v)
            for reason in gates: miss(reason,'BLOCKING')
            newer_runs=[o for o in v.values() if isinstance(o,AnalysisRun) and self._analysis_scope(v,o,security.object_id)==self._analysis_scope(v,analysis,security.object_id) and o.available_at>analysis.available_at]
            if newer_runs: miss('ANALYSIS_RECOMPUTE_REQUIRED','BLOCKING')
            for o in newer_runs: deps[key(o)]=o
            # 锚点只来自正式EventVersion和固定证据，不让后来媒体时间倒写first_seen。
            anchor=event_anchor(event)
            for r in anchor.proof_refs: take(r,EvidenceVersion)
            validate_reaction_window(anchor,request.reaction_window,at)
            context=take(request.context_ref,PricingContext) if request.context_ref else None
            if context and (context.event_ref!=packet.event_ref or context.security_ref!=request.security_ref): raise ValueError('PRICING_CONTEXT_SCOPE')
            checks={f.dimension:f for f in context.findings} if context else {}
            def outcome(code): return checks[code].outcome if code in checks else 'UNKNOWN'
            observations={}
            market_latest={}
            for o in v.values():
                if isinstance(o,MarketObservation):
                    k=observation_key(o)
                    if k not in market_latest or (o.available_at,o.version,o.object_id)>(market_latest[k].available_at,market_latest[k].version,market_latest[k].object_id):
                        market_latest[k]=o
            def obs(r,current=False):
                o=take(r,MarketObservation); observations[key(o)]=o
                for child in (o.session_ref,o.adjustment_ref,o.provider_ref,o.source_ref,o.instrument_ref):
                    take(child,(MarketSession,AdjustmentBasis,ProviderQualification,Source,SecurityVersion,MarketInstrument))
                if market_latest[observation_key(o)]!=o: miss('MARKET_OBSERVATION_RECOMPUTE_REQUIRED','BLOCKING')
                for code in quality(o,v,at,rules,current): miss(code,'BLOCKING' if current else 'DEGRADED')
                if o.pricing_mode=='HISTORICAL_REPLAY' and request.pricing_mode!='HISTORICAL_REPLAY': miss('MARKET_MODE_MISMATCH','BLOCKING')
                return o
            def prices(rs,target=True,current=False):
                points=[obs(r,current=current and i==len(rs)-1) for i,r in enumerate(rs)]
                if len(points)!=2: return points,None
                if any(o.observation_type!='PRICE' or (target and o.instrument_ref!=request.security_ref) for o in points): raise ValueError('PRICE_BINDING')
                value=price_return(points)
                if value is None: miss('PRICE_INCOMPARABLE','BLOCKING')
                return points,value
            points,raw=prices(request.price_refs,current=True)
            if len(points)!=2: miss('PRICE_MISSING','BLOCKING')
            elif Window(start=points[0].window.end,end=points[1].window.end)!=request.reaction_window: raise ValueError('REACTION_WINDOW_MISMATCH')
            pre,pre_return=prices(request.pre_price_refs)
            pre_window=Window(start=pre[0].window.end,end=pre[1].window.end) if len(pre)==2 else None
            pre_limit=min(anchor.first_seen_time,anchor.public_time or anchor.known_at)
            if pre_window and pre_window.end>pre_limit: raise ValueError('PRE_EVENT_BASELINE_CROSSES_ANCHOR')
            if not pre_window: miss('PRE_EVENT_BASELINE_MISSING')
            benchmarks=[take(r,BenchmarkSnapshot) for r in request.benchmark_refs]
            by_role={}
            for bm in benchmarks:
                if bm.benchmark_role in by_role: raise ValueError('BENCHMARK_ROLE_DUPLICATE')
                if bm.window!=request.reaction_window: raise ValueError('BENCHMARK_WINDOW')
                comp=take(bm.composition_ref,BenchmarkComposition)
                for r in comp.component_security_refs: take(r,SecurityVersion)
                for r in bm.price_refs:
                    bp=obs(r,current=r==bm.price_refs[-1])
                    if bp.currency!=security.currency: raise ValueError('BENCHMARK_CURRENCY_HOLD')
                if bm.return_value is None or bm.quality_status!='QUALIFIED': miss('BENCHMARK_UNQUALIFIED','BLOCKING')
                if bm.benchmark_role=='INDUSTRY':
                    ex=take(path.exposure_ref,CompanyExposure)
                    if path.world=='ECONOMIC' and comp.industry_ref!=ex.industry_ref: raise ValueError('INDUSTRY_BENCHMARK_SCOPE')
                    if comp.coverage_status!='COMPLETE_DECLARED_SCOPE': miss('INDUSTRY_COMPONENTS_INCOMPLETE')
                if latest(v,BenchmarkComposition)[comp.object_id]!=comp: miss('BENCHMARK_COMPONENTS_RECOMPUTE_REQUIRED','BLOCKING')
                by_role[bm.benchmark_role]=bm
            for role in ('MARKET','INDUSTRY'):
                if role not in by_role: miss(role+'_BENCHMARK_MISSING','BLOCKING')
            def relative(role): return raw-by_role[role].return_value if raw is not None and role in by_role and by_role[role].return_value is not None else None
            vol=obs(request.volume_ref) if request.volume_ref else None
            amount=obs(request.amount_ref) if request.amount_ref else None
            for o,kind in ((vol,'VOLUME'),(amount,'AMOUNT')):
                if o and (o.observation_type!=kind or o.instrument_ref!=request.security_ref or o.window!=request.reaction_window):
                    raise ValueError('FLOW_WINDOW：量额必须对应本证券和相同观察窗')
            vbase=[obs(r) for r in request.volume_baseline_refs]; abase=[obs(r) for r in request.amount_baseline_refs]
            vr_value,vn=volume_multiple(vol,vbase,v,anchor.known_at,rules)
            ar_value,an=volume_multiple(amount,abase,v,anchor.known_at,rules)
            if vr_value is None: miss('VOLUME_BASELINE_MISSING')
            if ar_value is None: miss('AMOUNT_BASELINE_MISSING')
            breadth=None
            if 'INDUSTRY' in by_role:
                comp=v[key(by_role['INDUSTRY'].composition_ref)]
                pair_obs=[obs(r) for r in request.diffusion_price_refs]
                member_companies={v[key(r)].company_ref.object_id for r in comp.component_security_refs}
                known_companies={v[key(r)].company_ref.object_id for r in history.request.exposure_refs
                    if v[key(r)].industry_ref==comp.industry_ref and v[key(r)].business_role==v[key(path.exposure_ref)].business_role}
                denominator_incomplete=not known_companies<=member_companies
                if len(pair_obs)%2: raise ValueError('DIFFUSION_PAIRS')
                pairs=list(zip(pair_obs[::2],pair_obs[1::2]))
                for a,b in pairs:
                    if Window(start=a.window.end,end=b.window.end)!=request.reaction_window: raise ValueError('DIFFUSION_WINDOW')
                pairs=[(a,b) for a,b in pairs if not quality(b,v,at,rules,True)]
                breadth=DiffusionFeatures(**diffusion(comp,pairs,by_role['INDUSTRY'].return_value,v))
                if denominator_incomplete:
                    breadth=breadth.model_copy(update=dict(coverage='INCOMPLETE',breadth_ratio=None,reacting_company_count=None,
                        median_relative_return=None,dispersion=None,leader_concentration=None,
                        eligible_company_count=len(known_companies|member_companies)))
                if breadth.coverage!='COMPLETE_DECLARED_SCOPE': miss('INDUSTRY_COMPONENTS_INCOMPLETE')
            cross_state='NOT_APPLICABLE'; converted=None; conversion=None
            if request.fx_ref and not request.cross_asset_ref: raise ValueError('FX_WITHOUT_CROSS_ASSET')
            if request.cross_asset_ref:
                cross=obs(request.cross_asset_ref)
                asset=take(cross.instrument_ref,MarketInstrument)
                # 跨资产需既有经济Impact明确目标，禁止为丰富维度强接其他资产。
                from ..ontology.contracts import ImpactVariable
                impacts=[v[key(r)] for r in path.node_refs if isinstance(v[key(r)],ImpactVariable)]
                compatible=(asset.asset_type=='COMMODITY' and any(i.target_object==asset.target_object for i in impacts)) or (
                    asset.asset_type=='FX' and any(i.variable_type=='FX' and i.fx_pair==asset.fx_pair for i in impacts))
                if not compatible: raise ValueError('CROSS_ASSET_MECHANISM_REQUIRED')
                errors=quality(cross,v,at,rules,True)
                cross_state='ASYNCHRONOUS' if errors else 'SYNCHRONOUS_CONTEXT'
                if errors: miss('CROSS_ASSET_DELAYED')
                elif cross.currency==security.currency:
                    converted=cross.value; conversion='SAME_CURRENCY_CONTEXT_NOT_EQUITY_RETURN'
                elif request.fx_ref:
                    fx=obs(request.fx_ref); pair=take(fx.instrument_ref,MarketInstrument).fx_pair
                    if fx.observation_type!='CROSS_ASSET' or fx.unit!='FX_RATE': raise ValueError('FX_UNIT_PAIR_HOLD')
                    if not pair or pair.base!=cross.currency or pair.quote!=security.currency: raise ValueError('FX_UNIT_PAIR_HOLD')
                    if quality(fx,v,at,rules,True) or fx.observed_at>cross.observed_at:
                        miss('FX_MISSING'); cross_state='UNKNOWN'
                    else:
                        converted=cross.value*fx.value
                        conversion=pair.base+'/'+pair.quote+' PIT_MULTIPLY_CONTEXT_ONLY'
                else: miss('FX_MISSING'); cross_state='UNKNOWN'
            sessions=set()
            history_prices=[obs(r) for r in request.prior_session_price_refs]
            if len(history_prices)%2: raise ValueError('SESSION_PRICE_PAIRS')
            for a,b in zip(history_prices[::2],history_prices[1::2]):
                if a.instrument_ref!=request.security_ref or a.window.end<anchor.known_at or b.window.end>request.reaction_window.start:
                    raise ValueError('SESSION_TREND_WINDOW')
                if price_return([a,b]) is not None and price_return([a,b])>0:
                    sessions.add(b.window.end.astimezone(timezone(timedelta(minutes=v[key(b.session_ref)].utc_offset_minutes))).date())
            if raw is not None and raw>0:
                sessions.add(request.reaction_window.end.astimezone(timezone(timedelta(minutes=v[key(points[-1].session_ref)].utc_offset_minutes))).date())
            novelty_objects=[o for o in v.values() if isinstance(o,NoveltyDecision) and o.status in ('READY','DEGRADED') and o.evidence_ref in event.evidence_refs]
            novel=max(novelty_objects,key=lambda o:(o.available_at,o.object_id),default=None)
            if novel: deps[key(novel)]=novel
            else: miss('NOVELTY_UNDETERMINED')
            novelty=novel.classification if novel else 'UNDETERMINED'
            thesis=selected.confidence_band if selected else 'UNKNOWN'
            extra_values={}
            for r,kind in ((request.volatility_ref,'VOLATILITY'),(request.turnover_ref,'TURNOVER')):
                value=obs(r) if r else None
                if value and (value.instrument_ref!=request.security_ref or value.observation_type!=kind or value.window!=request.reaction_window):
                    raise ValueError('EXTRA_MARKET_WINDOW')
                extra_values[kind.lower()]=value.value if value and not quality(value,v,at,rules) else None
            breadth_delta=None
            if request.previous_features_ref:
                previous=take(request.previous_features_ref,MarketReactionFeatures)
                if previous.security_ref!=request.security_ref or previous.anchor.event_ref.object_id!=event.object_id or previous.reaction_window.end>request.reaction_window.start:
                    raise ValueError('DIFFUSION_TREND_WINDOW')
                old_bms=[v[key(r)] for r in previous.benchmark_refs]
                same=any(b.benchmark_role=='INDUSTRY' and 'INDUSTRY' in by_role and b.composition_ref==by_role['INDUSTRY'].composition_ref for b in old_bms)
                if same and breadth and previous.diffusion and breadth.breadth_ratio is not None and previous.diffusion.breadth_ratio is not None:
                    breadth_delta=breadth.breadth_ratio-previous.diffusion.breadth_ratio
            feature_data=dict(traded_session_count=len(sessions),breadth_delta=breadth_delta,**extra_values,security_ref=ref(security),anchor=anchor.model_dump(mode='json'),reaction_window=request.reaction_window.model_dump(mode='json'),
                pre_event_window=pre_window.model_dump(mode='json') if pre_window else None,observation_refs=refs(observations.values()),
                benchmark_refs=refs(benchmarks),raw_return=raw,market_relative_return=relative('MARKET'),industry_relative_return=relative('INDUSTRY'),
                pre_event_return=pre_return,volume_ratio=vr_value,amount_ratio=ar_value,volume_sample_n=vn,amount_sample_n=an,
                diffusion=breadth.model_dump(mode='json') if breadth else None,cross_asset_state=cross_state,
                converted_cross_asset_value=converted,conversion_basis=conversion,
                converted_currency=security.currency if converted is not None else None,converted_unit=cross.unit if converted is not None else None)
            common=dict(as_of=at.isoformat(),observed_at=request.reaction_window.end.isoformat(),pricing_mode=request.pricing_mode,
                provenance_zh='固定PIT输入确定性工程研究；不是因果证明、Alpha或投资建议')
            staged=[]
            def stage(cls,suffix,payload):
                obj_id=identity+suffix
                staged.append((cls,obj_id,{**common,**payload}))
                return VersionRef(object_id=obj_id,version=version)
            fref=stage(MarketReactionFeatures,':FEATURES',feature_data)
            buyer_refs=[]; buyer_good=False
            for index,buyer in enumerate(request.next_buyers):
                bs='PLAUSIBLE'; br=[]
                bp=[take(r,TransmissionPath) for r in buyer.supporting_path_refs]
                bo=[obs(r) for r in buyer.supporting_observation_refs]
                if any(p.event_ref!=vr(event) or p.security_ref!=request.security_ref or p.world!='ECONOMIC' or vr(p) not in packet.path_refs for p in bp):
                    raise ValueError('NEXT_BUYER_PATH_SCOPE')
                if buyer.buyer_type=='SHORT_COVERING':
                    bs='REJECTED'; br.append('A_SHARE_SHORT_COVERING_NOT_ESTABLISHED')
                elif buyer.buyer_type=='UNKNOWN':
                    bs='UNKNOWN'; br.append('BUYER_UNKNOWN')
                elif not all((buyer.why_not_already_present,buyer.expected_trigger,buyer.failure_condition,bp,bo,
                              buyer.non_presence_evidence_ref,buyer.quoted_span)):
                    bs='WEAK'; br.append('BUYER_SPECIFIC_MECHANISM_MISSING')
                else:
                    proof=take(buyer.non_presence_evidence_ref,EvidenceVersion); self._quote(v,vr(proof),buyer.quoted_span)
                    if not all(text in buyer.quoted_span for text in (buyer.why_not_already_present,buyer.expected_trigger,buyer.failure_condition)):
                        bs='WEAK'; br.append('BUYER_UNSUPPORTED_EXPLANATION')
                    elif any(o.instrument_ref!=request.security_ref or quality(o,v,at,rules) for o in bo):
                        bs='WEAK'; br.append('BUYER_OBSERVATION_UNQUALIFIED')
                    else: bs='SUPPORTED'
                buyer_good |= bs=='SUPPORTED'
                buyer_refs.append(stage(NextBuyerHypothesis,':BUYER:'+str(index),{**buyer.model_dump(mode='json'),
                    'hypothesis_status':bs,'reason_codes_buyer':br}))
            if not buyer_good: miss('NEXT_BUYER_NOT_SPECIFIC')
            for obj in list(deps.values()):
                if isinstance(obj,PricingEnvelope):
                    newest=latest(v,type(obj)).get(obj.object_id)
                    if newest is not None and key(newest)!=key(obj):
                        miss(type(obj).__name__.upper()+'_RECOMPUTE_REQUIRED','BLOCKING')
                        deps[key(newest)]=newest
                    if obj.pricing_mode=='HISTORICAL_REPLAY' and request.pricing_mode!='HISTORICAL_REPLAY':
                        miss('PRICING_INPUT_MODE_MISMATCH','BLOCKING')
            triggered=relative('INDUSTRY') is not None and abs(relative('INDUSTRY'))<rules.low_reaction
            nrchecks=[checks[c] for c in NONREACTION if c in checks]
            explained=any(f.outcome=='YES' for f in nrchecks) or (pre_return is not None and pre_return>=rules.large_relative) or (raw is not None and raw>=rules.noticeable_relative and relative('INDUSTRY') is not None and abs(relative('INDUSTRY'))<rules.low_reaction)
            nstatus='DATA_INSUFFICIENT'
            complete_nr=all(outcome(c)!='UNKNOWN' for c in NONREACTION) and pre_return is not None
            if block: nstatus='HOLD'
            elif explained: nstatus='EXPLAINED_NON_REACTION'
            elif triggered and complete_nr and thesis in ('HIGH','VERY_HIGH') and outcome('DISSEMINATION')=='YES':
                nstatus='UNEXPLAINED_NON_REACTION'
            gap=triggered and nstatus=='UNEXPLAINED_NON_REACTION'
            nref=stage(NonReactionInvestigation,':NONREACTION',dict(checks=[f.model_dump(mode='json') for f in nrchecks],
                investigation_status=nstatus,triggered=triggered,recognition_gap=gap,basis_refs=refs(deps.values())))
            causechecks=[checks[c] for c in CAUSES if c in checks]
            other=any(f.outcome=='YES' for f in causechecks)
            causes=['FIXED_SCOPE_NO_CAUSAL_PROOF']
            if pre_return is not None and pre_return>=rules.large_relative: other=True; causes.append('PRE_EVENT_TREND_PRESENT')
            if raw is not None and raw>0 and relative('INDUSTRY') is not None and abs(relative('INDUSTRY'))<rules.low_reaction:
                other=True; causes.append('SECTOR_RALLY_POSSIBLE')
            cstatus='MULTI_CAUSE' if other else 'CURRENT_EVENT_DOMINANT' if all(outcome(c)=='NO' for c in CAUSES) else 'CAUSE_UNKNOWN'
            if outcome('OTHER_EVENT')=='YES' and outcome('IMMATERIAL')=='YES': cstatus='ALTERNATIVE_CAUSE_STRONG'
            cref=stage(AlternativeCauseSearch,':CAUSE',dict(checks=[f.model_dump(mode='json') for f in causechecks],
                cause_status=cstatus,reason_codes_cause=causes,basis_refs=refs(deps.values())))
            if cstatus=='CAUSE_UNKNOWN': miss('ALTERNATIVE_CAUSE_SEARCH_INCOMPLETE')
            if triggered and nstatus=='DATA_INSUFFICIENT': miss('NON_REACTION_UNEXPLAINED_DATA_GAP')
            # 类型验证仍由Pydantic；临时对象只供纯函数，不提前持久化。
            from types import SimpleNamespace
            features=SimpleNamespace(**{**feature_data,'diffusion':breadth})
            result=classify_dimensions(features,rules=rules,thesis=thesis,novelty=novelty,
                dissemination=outcome('DISSEMINATION'),buyer=buyer_good,nonreaction=SimpleNamespace(recognition_gap=gap),
                cause=cstatus,remaining_diffusion=outcome('REMAINING_DIFFUSION'),sessions=len(sessions),
                counter=outcome('COUNTEREVIDENCE')=='YES' or (red is not None and red.red_team.verdict=='TARGET_INVALIDATED'))
            recognition,price_in,crowd,edge,reversal,dimension_reasons=result
            if block: price_in='UNKNOWN'; edge='HOLD'
            mref=stage(MissingDimensions,':MISSING',dict(items=[m.model_dump(mode='json') for m in missing]))
            assessment=dict(request=request.model_dump(mode='json'),event_ref=ref(event),security_ref=ref(security),
                research_refs=refs([analysis,packet,history,path,*([primary] if primary else []),*([red] if red else []),*([adj] if adj else [])]),
                market_observation_refs=refs(observations.values()),benchmark_refs=refs(benchmarks),features_ref=ref(fref),
                recognition_state=recognition,price_in_band=price_in,crowding_band=crowd,remaining_edge=edge,reversal_risk=reversal,
                next_buyer_refs=[ref(r) for r in buyer_refs],non_reaction_ref=ref(nref),alternative_cause_ref=ref(cref),
                missing_dimensions_ref=ref(mref),dimension_reasons=dimension_reasons,thesis_strength=thesis,novelty=novelty,
                assessment_status='HOLD' if block else 'ENGINEERING_ONLY',
                hold_reasons=sorted(set([*HOLDS,'HOLD_MARKET_DATA_PROVIDER_LIVE','HOLD_PRICING_POLICY_CALIBRATION',*block])))
            all_dependencies=list(deps.values())
            for cls,oid,payload in staged:
                self._put(conn,all_view,batch,cls,oid,version,payload,all_dependencies)
            # 同事务正式引用输出；这些输出在publication fence完成前全部不可见。
            output_refs=[VersionRef(object_id=oid,version=version) for _,oid,_ in staged]
            self._put(conn,all_view,batch,PricingAssessment,identity,version,{**common,**assessment},[*all_dependencies,*output_refs])
            self.ledger.fault('after_pricing_assessment')
        self.ledger._write('P8:ASSESS:'+identity+':'+str(version),digest(request.model_dump(mode='json')),write)
        return self.ledger.get(identity,version)

    def current(self,assessment_ref,*,as_of,pricing_mode):
        at=TypeAdapter(UTCDateTime).validate_python(as_of); v=self.view(at)
        a=self.load(v,assessment_ref,PricingAssessment)
        if a.pricing_mode!=pricing_mode: raise ValueError('PRICING_MODE_ISOLATION')
        reasons=set()
        history=v[key(v[key(v[key(a.request.analysis_ref)].packet_ref)].mapping_history_ref)]
        reasons.update(self.research.gates(history,v)[0])
        prior_inputs={key(r) for r in a.input_version_refs}
        instruments={v[key(r)].instrument_ref.object_id for r in a.market_observation_refs}
        for obj in v.values():
            if isinstance(obj,MarketObservation) and obj.instrument_ref.object_id in instruments and obj.available_at>a.available_at:
                reasons.add('MARKET_OBSERVATION_RECOMPUTE_REQUIRED')
            if isinstance(obj,(BenchmarkComposition,AdjustmentBasis,MarketSession,ProviderQualification,PricingContext,PricingPolicy)):
                if any(oid==obj.object_id and ver<obj.version for oid,ver in prior_inputs): reasons.add(type(obj).__name__.upper()+'_RECOMPUTE_REQUIRED')
            if isinstance(obj,AnalysisRun) and self._analysis_scope(v,obj,a.security_ref.object_id)==self._analysis_scope(v,v[key(a.request.analysis_ref)],a.security_ref.object_id) and obj.available_at>a.available_at:
                reasons.add('ANALYSIS_RECOMPUTE_REQUIRED')
        policy=v[key(a.request.policy_ref)]
        if a.request.price_refs:
            o=v[key(a.request.price_refs[-1])]
            reasons.update(quality(o,v,at,policy.rules,True))
        return dict(assessment=a,current_remaining_edge='HOLD' if reasons else a.remaining_edge,
                    freshness='RECOMPUTE_REQUIRED' if reasons else 'AS_RECORDED',recompute_reasons=sorted(reasons),
                    formal_positive_remaining_edge=False)

    def report(self,assessment_ref,*,as_of,pricing_mode):
        state=self.current(assessment_ref,as_of=as_of,pricing_mode=pricing_mode); a=state['assessment']
        return dict(声明=['ENGINEERING_DEMO','NO_ALPHA_CLAIM','NO_INVESTMENT_ADVICE'],模式=a.pricing_mode,
            市场认知=a.recognition_state,已定价=a.price_in_band,拥挤=a.crowding_band,剩余空间=state['current_remaining_edge'],
            反转风险=a.reversal_risk,研究状态=a.assessment_status,正式正向空间=False,
            输入截止=a.as_of.isoformat(),结果可用=a.available_at.isoformat(),重算原因=state['recompute_reasons'],
            缺失维度=[m.model_dump(mode='json') for m in self.ledger.get(a.missing_dimensions_ref.object_id,a.missing_dimensions_ref.version).items],
            HOLD=list(a.hold_reasons))
