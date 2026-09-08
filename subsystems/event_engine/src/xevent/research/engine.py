"""一次主研究、一次独立反方、必要时一次裁定；调用前记预算，崩溃后不盲目重发。"""
import json
from types import SimpleNamespace
from pydantic import ValidationError
from ..ledger.store import digest, ref
from ..registry.engine import key, refs, latest
from .contracts import (ResearchPacket,ModelConfig,PromptVersion,HypothesisSet,RedTeamReport,Adjudication,
    ModelResult,CostLedger,AnalysisRun,AnalysisStart)
from .packet import ResearchStore, vr
from .provider import GUARD, ProviderResponse, invoke
from .validation import validate_output, ResearchInvalid, downstream_input, validate_decision

OUTPUTS={'PRIMARY':HypothesisSet,'RED_TEAM':RedTeamReport,'ADJUDICATION':Adjudication}
FIELDS={'PRIMARY':'primary','RED_TEAM':'red_team','ADJUDICATION':'adjudication'}
TEMPLATES={'PRIMARY':'primary_zh','RED_TEAM':'red_team_zh','ADJUDICATION':'adjudication_zh'}
HOLDS=['HOLD_MODEL_PROVIDER_LIVE','HOLD_REAL_COMPANY_EXPOSURE_COVERAGE','HOLD_HISTORICAL_UNIVERSE_COVERAGE',
    'HOLD_PRE_1992_CALENDAR','HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION','HOLD_MODEL_USAGE_COST_UNVERIFIED']


class ResearchEngine(ResearchStore):
    def run(self, identity, packet_ref, provider):
        # 一个进程内同Ledger互斥，避免相同run并发重复调用；没有多Agent会话。
        with self.ledger.lock:
            return self._run(identity,packet_ref,provider)

    def _run(self, identity, packet_ref, provider):
        self.ledger.recover()
        started=self.ledger.now()
        view=self.view(started)
        packet=self.registry.input(view,packet_ref,ResearchPacket)
        model=view[key(packet.model_config_ref)]; prompt=view[key(packet.prompt_version_ref)]
        fingerprint=digest(ref(packet))
        prior=view.get((identity,1)); start=view.get((identity+':START',1))
        if start and start.request_hash!=fingerprint: raise ValueError('IDEMPOTENCY_CONFLICT')
        if prior:
            if not isinstance(prior,AnalysisRun): raise ValueError('RESEARCH_ID_TYPE')
            return prior
        costs=[]; primary_result=red_result=adj_result=None
        reasons=list(packet.gate_reasons)
        if start:
            # 真实Provider不可证明exactly-once；已预留但无最终run时只隔离，绝不静默再计费。
            started=start.started_at
            reasons.append('HOLD_INCOMPLETE_PREVIOUS_RUN')
            costs=[r for r in latest(view,CostLedger).values() if r.analysis_run_id==identity]
        else:
            start=self.save('AnalysisStart',identity+':START',dict(packet_ref=ref(packet),started_at=started.isoformat(),
                request_hash=fingerprint,as_of=packet.as_of.isoformat(),provenance_zh='调用前耐久化研究身份；中断后禁止盲目重发'),[packet])
        original_view=self.view(packet.as_of)
        history=original_view[key(packet.mapping_history_ref)]
        gate_view=original_view if packet.research_mode=='HISTORICAL_REPLAY' else self.view(self.ledger.now())
        gates,_=self.gates(history,gate_view)
        reasons.extend(gates)
        binding=(getattr(provider,'provider_id',None),getattr(provider,'model_identifier',None))
        if binding!=(model.provider_id,model.model_identifier) or not getattr(provider,'is_mock',False):
            reasons.append('PROVIDER_UNAVAILABLE')
        if model.budget_policy.max_cost is not None:
            reasons.append('HOLD_COST_PRICE_UNKNOWN')
        spent_requests=0; reserved_tokens=0; repairs=0
        base=self.provider_data(packet)

        def call(kind, primary=None, red=None):
            nonlocal spent_requests,reserved_tokens,repairs
            data={**base}
            if primary: data['primary']=downstream_input(primary.primary)
            if red: data['red_team']=downstream_input(red.red_team)
            system=GUARD+'\n'+getattr(prompt,TEMPLATES[kind])
            schema=OUTPUTS[kind].model_json_schema()
            cache_key=digest([packet.packet_hash,packet.research_mode,model.content_hash,prompt.content_hash,kind,data,system,schema])
            cached=next((r for r in self.ledger.history(as_of=self.ledger.now(),kind='ModelResult') if r.cache_key==cache_key),None)
            inputs=[packet,model,prompt,start,*([primary] if primary else []),*([red] if red else [])]
            cost_base=dict(analysis_run_id=identity,provider=model.provider_id,model=model.model_identifier,
                call_type=kind,cache_key=cache_key,as_of=packet.as_of.isoformat(),provenance_zh='逐调用审计，未知价格与用量不补零')
            if cached:
                validate_output(getattr(cached,FIELDS[kind]),packet,original_view,self.ledger,primary.primary if primary else None,red.red_team if red else None)
                cost=self.save('CostLedger',identity+':'+kind+':CACHE',dict(**cost_base,request_count=0,reserved_output=0,
                    cache_hit=True,call_status='SUCCESS'),[*inputs,cached])
                costs.append(cost)
                return cached
            attempt=0
            while True:
                if spent_requests>=model.budget_policy.max_requests or reserved_tokens+model.max_output>model.budget_policy.max_output_tokens_total:
                    cost=self.save('CostLedger',identity+':'+kind+':BUDGET',dict(**cost_base,request_count=0,reserved_output=0,
                        call_status='BUDGET_EXHAUSTED'),inputs)
                    costs.append(cost); reasons.append('HOLD_BUDGET_EXHAUSTED')
                    return None
                cost_id=identity+':'+kind+':'+str(attempt)
                reserved=self.save('CostLedger',cost_id,dict(**cost_base,request_count=1,reserved_output=model.max_output,
                    retry=bool(attempt),call_status='RESERVED'),inputs)
                costs.append(reserved); spent_requests+=1; reserved_tokens+=model.max_output
                self.ledger.fault('after_model_reservation')
                status='SUCCESS'; response=None; parsed=None; response_hash=None
                try:
                    request_data={**data,'repair_error_code':'INVALID_STRUCTURED_OUTPUT'} if attempt else data
                    response=invoke(provider,call_type=kind,system=system,
                        untrusted_data=request_data,output_schema=schema,max_output=model.max_output,temperature=model.temperature,
                        timeout_seconds=model.timeout_seconds)
                    response=ProviderResponse.model_validate(response)
                    response_hash=digest(response.content)
                    if len(response.content.encode('utf-8'))>model.max_output*32 or (response.output_usage is not None and response.output_usage>model.max_output):
                        raise ResearchInvalid('BUDGET_EXHAUSTED','输出超出预留上限')
                    parsed=OUTPUTS[kind].model_validate_json(response.content)
                    validate_output(parsed,packet,original_view,self.ledger,primary.primary if primary else None,red.red_team if red else None)
                except TimeoutError:
                    status='TIMEOUT'
                except ResearchInvalid as exc:
                    status=exc.status
                except ValidationError:
                    status='INVALID_SCHEMA'
                except Exception:
                    # Provider异常消息可能携带认证信息；只存分类，不存异常字符串。
                    status='PROVIDER_UNAVAILABLE'
                cost=self.save('CostLedger',cost_id,dict(**cost_base,request_count=1,reserved_output=model.max_output,
                    retry=bool(attempt),call_status=status,timeout=status=='TIMEOUT',response_hash=response_hash,
                    input_usage=response.input_usage if response else None,output_usage=response.output_usage if response else None),inputs,version=2)
                costs[-1]=cost
                if status=='SUCCESS':
                    result=self.save('ModelResult',identity+':'+kind,dict(packet_ref=ref(packet),call_type=kind,
                        **{FIELDS[kind]:parsed.model_dump(mode='json')},cache_key=cache_key,response_hash=response_hash,
                        as_of=packet.as_of.isoformat(),research_mode=packet.research_mode,
                        provenance_zh='已通过Schema、引用与数值门槛的公开结论依据'),[*inputs,cost])
                    self.ledger.fault('after_model_result')
                    return result
                if status in ('INVALID_SCHEMA','INVALID_REFERENCE','INVALID_NUMERIC_CLAIM') and repairs<model.retry_limit:
                    repairs+=1; attempt+=1
                    continue
                reasons.append('HOLD_BUDGET_EXHAUSTED' if status=='BUDGET_EXHAUSTED' else status)
                return None

        # freshness/输入HOLD可以进行显式降级研究，但模型不能发表TARGET；关键新鲜度失效则不调用。
        blocked=bool(start and 'HOLD_INCOMPLETE_PREVIOUS_RUN' in reasons) or any(r not in packet.gate_reasons for r in reasons)
        if not blocked:
            primary_result=call('PRIMARY')
            if primary_result:
                red_result=call('RED_TEAM',primary_result)
                if red_result:
                    conflict=(red_result.red_team.recommended_id!=primary_result.primary.selected_id and
                        red_result.red_team.verdict in ('TARGET_INVALIDATED','ALT_STRONGER','NULL_PREFERRED'))
                    if conflict and model.allow_adjudication:
                        adj_result=call('ADJUDICATION',primary_result,red_result)
        final_result=None; decision_source='HOLD_GATE'
        selected=None; choice='HOLD'; analysis_status='HOLD'
        if primary_result and red_result:
            hypotheses=primary_result.primary
            selected=adj_result.adjudication.selected_id if adj_result else red_result.red_team.recommended_id
            if adj_result:
                decision_source='ADJUDICATION'; final_result=adj_result
            elif selected!=hypotheses.selected_id:
                decision_source='RED_TEAM'; final_result=red_result
            else:
                decision_source='PRIMARY'; final_result=primary_result
            # 模型运行期间上游也可能变化；发布前重新检查，同样不能让模型豁免。
            gates,_=self.gates(history,original_view if packet.research_mode=='HISTORICAL_REPLAY' else self.view(self.ledger.now()))
            reasons.extend(gates)
            if not reasons:
                choice=next(h.type for h in (hypotheses.target,*hypotheses.alternatives,hypotheses.null_hypothesis) if h.hypothesis_id==selected)
                analysis_status='MOCK_PASS'
            else:
                selected=None; choice='NULL'
        if analysis_status=='HOLD':
            decision_source='HOLD_GATE'; final_result=None; selected=None
        finished=self.ledger.now()
        inputs=[packet,model,prompt,start,*costs,*[r for r in (primary_result,red_result,adj_result) if r],
            self.ledger.get(packet.search_coverage_ref.object_id,packet.search_coverage_ref.version)]
        payload=dict(packet_ref=ref(packet),primary_result_ref=ref(primary_result) if primary_result else None,
            red_team_ref=ref(red_result) if red_result else None,adjudication_ref=ref(adj_result) if adj_result else None,
            decision_source=decision_source,final_result_ref=ref(final_result) if final_result else None,final_hypothesis_id=selected,final_choice=choice,
            model_config_refs=[ref(model)],prompt_refs=[ref(prompt)],cost_ledger_refs=refs(costs),search_coverage_ref=ref(packet.search_coverage_ref),
            started_at=started.isoformat(),completed_at=finished.isoformat(),as_of=packet.as_of.isoformat(),research_mode=packet.research_mode,
            analysis_status=analysis_status,hold_reasons=sorted(set([*HOLDS,*reasons])),provenance_zh='模型研究公开审计结果；Mock通过不代表真实模型或Alpha有效')
        validate_decision(SimpleNamespace(**payload),primary_result,red_result,adj_result)
        return self.save('AnalysisRun',identity,payload,inputs)

    def report(self, run_ref):
        run=self.ledger.get(run_ref.object_id,run_ref.version)
        if not isinstance(run,AnalysisRun): raise ValueError('REPORT_REFERENCE')
        packet=self.ledger.get(run.packet_ref.object_id,run.packet_ref.version)
        primary=self.ledger.get(run.primary_result_ref.object_id,run.primary_result_ref.version).primary if run.primary_result_ref else None
        red=self.ledger.get(run.red_team_ref.object_id,run.red_team_ref.version).red_team if run.red_team_ref else None
        return {'声明':'仅工程Mock结构化研究，不代表真实模型研究有效或投资建议','研究状态':run.analysis_status,
            '研究模式':run.research_mode,'决定来源':run.decision_source,
            '自由文本资格':'INFERENCE_ONLY / RESEARCH_COMMENTARY，无正式FACT资格',
            '最终假设类型':run.final_choice,'最终假设':run.final_hypothesis_id,'输入截止':packet.as_of.isoformat(),
            '结果可用':run.available_at.isoformat(),'假设集合':primary.model_dump(mode='json') if primary else None,
            '反方审查':red.model_dump(mode='json') if red else None,'HOLD':list(run.hold_reasons)}
