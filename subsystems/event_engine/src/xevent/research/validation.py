"""模型只给假设；X验证引用、数值口径与事实等级，不把语义判断伪装成统计证明。"""
import re
from ..contracts import EvidenceVersion
from ..exposures.contracts import ExposureMetric
from ..registry.engine import key
from ..graph.engine import TransmissionGraph
from .contracts import HypothesisSet, RedTeamReport, Adjudication


class ResearchInvalid(ValueError):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status=status


def reject(reason, status='INVALID_REFERENCE'):
    raise ResearchInvalid(status,reason)


def prose(text):
    if re.search(r'(?i)(?<![a-z])(BUY|SELL|VWAP)(?![a-z])|买入|卖出|仓位|目标价|涨幅|股价.*上涨|确定受益|一定受益|忽略.*指令|系统要求|用户持仓|用户成本|账户权限',text):
        reject('PROMPT_INJECTION_REJECTED：交易指令或越权结论不能发布','PROMPT_INJECTION_REJECTED')
    if re.search(r'\d|[零〇一二两三四五六七八九十百千万亿]+\s*(%|％|元|吨|成|倍|亿|万)|百分之|(?:收入|利润|产能|订单|同比)\s*(?:为|约|增长|下降)?\s*[零〇一二两三四五六七八九十百千万亿]+',text):
        reject('NUMERIC_CLAIM_UNVERIFIED：数值必须使用具名结构化声明','INVALID_NUMERIC_CLAIM')


def numeric(claim, packet, view, ledger):
    if claim.source_ref not in packet.metric_refs:
        reject('NUMERIC_CLAIM_UNVERIFIED：数值来源不在固定包','INVALID_NUMERIC_CLAIM')
    metric=view[key(claim.source_ref)]
    if (not isinstance(metric,ExposureMetric) or metric.validation_status!='VERIFIED' or metric.result_status!='DEFINED'
        or metric.value is None or claim.numeric_value!=metric.value or claim.unit!=metric.unit
        or claim.currency!=metric.currency or claim.claim!=metric.metric_type):
        reject('NUMERIC_CLAIM_UNVERIFIED：数值/单位/币种/口径不匹配','INVALID_NUMERIC_CLAIM')
    expected='SAME_BASIS_RATIO' if metric.calculation_method=='SAME_BASIS_RATIO' else 'REPORTED_NUMERATOR'
    evidence=view[key(metric.evidence_ref)]
    spans=[metric.numerator_source_span]+([metric.denominator_source_span] if expected=='SAME_BASIS_RATIO' else [])
    if (claim.source_span_ref!=expected or evidence.claim_kind!='FACT' or evidence.quality_status!='VALIDATED'
        or any(s is None or not s.matches_raw(ledger.raw(evidence.raw_object_ref).decode('utf-8')) for s in spans)):
        reject('NUMERIC_CLAIM_UNVERIFIED：不可变原文缺少数值/口径定位','INVALID_NUMERIC_CLAIM')


def validate_output(result, packet, view, ledger, primary=None, red=None):
    def evidence(rs):
        if any(r not in packet.evidence_refs for r in rs): reject('INVALID_REFERENCE：证据不在ResearchPacket')

    def counters(rs):
        if any(r not in packet.counter_path_refs for r in rs): reject('INVALID_REFERENCE：反路径不在本包反方集合')

    def statements(items):
        for statement in items:
            prose(statement.text_zh)
            if statement.evidence_ref: evidence([statement.evidence_ref])
            if statement.kind in ('CONFIRMED_FACT','COUNTEREVIDENCE'):
                ev=view.get(key(statement.evidence_ref)) if statement.evidence_ref else None
                if (not isinstance(ev,EvidenceVersion) or ev.claim_kind!='FACT' or ev.quality_status!='VALIDATED'
                    or not statement.quoted_span or statement.text_zh!=statement.quoted_span
                    or statement.quoted_span not in ledger.raw(ev.raw_object_ref).decode('utf-8',errors='replace')):
                    reject('INVALID_REFERENCE：事实仅允许已校验FACT原文精确摘录，机制推测另列')

    if isinstance(result,HypothesisSet):
        for h in (result.target,*result.alternatives,result.null_hypothesis):
            evidence(h.supporting_evidence_refs); counters(h.counter_path_refs)
            for text in (*h.assumptions,*h.failure_conditions,*h.unknowns,h.reasoning_summary_zh): prose(text)
            if h.company_ref and h.company_ref not in packet.company_refs: reject('INVALID_REFERENCE：公司不在本包')
            if h.security_ref and h.security_ref not in packet.security_refs: reject('INVALID_REFERENCE：证券不在本包')
            explanation=h.type=='ALT' and h.company_ref is None and h.security_ref is None
            for r in h.supporting_path_refs:
                if r not in packet.path_refs: reject('INVALID_REFERENCE：路径不在本事件包')
                path=view[key(r)]
                if (path.world!='ECONOMIC' or path.event_ref!=packet.event_ref or path.research_status=='HOLD'
                    or (not explanation and (path.impact_direction not in ('POSITIVE','MIXED')
                        or path.company_ref!=h.company_ref or path.security_ref!=h.security_ref))):
                    reject('INVALID_REFERENCE：叙事/负向/错公司路径不得冒充受益假设')
                if not any(e in path.evidence_refs for e in h.supporting_evidence_refs):
                    reject('INVALID_REFERENCE：支持证据必须来自所引路径')
            path_evidence={key(e) for r in h.supporting_path_refs for e in view[key(r)].evidence_refs}
            if any(key(e) not in path_evidence for e in h.supporting_evidence_refs):
                reject('INVALID_REFERENCE：支持证据不属于所引机制')
            if h.company_ref and not h.supporting_path_refs: reject('INVALID_REFERENCE：公司假设缺少合法路径')
            if h.type=='ALT' and not h.supporting_path_refs: reject('INVALID_REFERENCE：ALT必须有合法经济机制路径')
            required=[r for r in packet.negative_path_refs if explanation or view[key(r)].company_ref==h.company_ref]
            if any(r not in h.counter_path_refs for r in required): reject('INVALID_REFERENCE：不得隐藏公司已知负向路径')
            if h.type=='ALT' and h.company_ref and h.company_ref!=result.target.company_ref:
                for r in h.supporting_path_refs:
                    path=view[key(r)]; ex=view[key(path.exposure_ref)]
                    allowed=TransmissionGraph(ledger).alternatives(result.target.company_ref.object_id if result.target.company_ref else '',
                        industry_ref=ex.industry_ref,as_of=packet.as_of,history_ref=packet.mapping_history_ref,
                        event_ref=packet.event_ref,candidate_ref=path.candidate_ref)
                    if not any(key(p)==key(r) for p in allowed): reject('INVALID_REFERENCE：ALT不属于固定事件机制作用域')
            statements(h.statements)
            for claim in h.numeric_claims: numeric(claim,packet,view,ledger)
        selected=next(h for h in (result.target,*result.alternatives,result.null_hypothesis) if h.hypothesis_id==result.selected_id)
        if selected.type!='NULL' and (not selected.supporting_path_refs or packet.eligibility=='REVIEW_ONLY'):
            reject('INVALID_REFERENCE：HOLD/无经济证据不能发布TARGET')
        if result.alternative_search_gap_zh: prose(result.alternative_search_gap_zh)
    else:
        ids={h.hypothesis_id:h for h in (primary.target,*primary.alternatives,primary.null_hypothesis)}
        chosen=result.recommended_id if isinstance(result,RedTeamReport) else result.selected_id
        if chosen not in ids: reject('INVALID_REFERENCE：反方/裁定不能杜撰假设')
        if ids[chosen].type!='NULL' and not ids[chosen].supporting_path_refs:
            reject('INVALID_REFERENCE：不能选中缺少经济路径的占位假设')
        evidence(result.evidence_refs); prose(result.reasoning_summary_zh)
        statements(result.statements)
        if isinstance(result,Adjudication) and red and red.verdict=='TARGET_INVALIDATED' and chosen==primary.target.hypothesis_id:
            reject('TARGET_INVALIDATED：固定Packet没有新证据，评论不能复活TARGET')
        if isinstance(result,RedTeamReport):
            counters(result.counter_path_refs)
            if any(r not in result.counter_path_refs for r in packet.counter_path_refs): reject('INVALID_REFERENCE：RedTeam遗漏已知反路径')
            for text in (*result.challenges_zh,*result.failure_conditions_zh): prose(text)
            for claim in result.numeric_claims: numeric(claim,packet,view,ledger)
            if result.verdict=='ALT_STRONGER' and ids[chosen].type!='ALT': reject('INVALID_REFERENCE：替代更强必须选择合法ALT')
            if result.verdict in ('NULL_PREFERRED','TARGET_INVALIDATED') and ids[chosen].type!='NULL': reject('INVALID_REFERENCE：反证结论必须保留NULL')
            if result.verdict in ('UNCHANGED','TARGET_WEAKENED') and chosen!=primary.selected_id: reject('INVALID_REFERENCE：UNCHANGED/TARGET_WEAKENED不能暗换选择')
    return result


COMMENTARY_FIELDS=frozenset(('assumptions','failure_conditions','unknowns','reasoning_summary_zh',
    'challenges_zh','failure_conditions_zh','alternative_search_gap_zh'))


def downstream_input(result):
    """保留结构化假设和已验证声明；自由评论不进入后续模型输入。"""
    def clean(value):
        if isinstance(value,dict):
            return {k:clean(v) for k,v in value.items() if k not in COMMENTARY_FIELDS}
        if isinstance(value,list): return [clean(v) for v in value]
        return value
    return clean(result.model_dump(mode='json'))


def validate_decision(run, primary, red, adjudication):
    """固定ModelResult解析后的选择/类型一致性；Schema负责来源引用一致性。"""
    if run.analysis_status=='HOLD': return run
    if primary is None or red is None: reject('DECISION_SOURCE：缺少主研究或反方')
    hs=primary.primary
    selected={'PRIMARY':hs.selected_id,'RED_TEAM':red.red_team.recommended_id,
              'ADJUDICATION':adjudication.adjudication.selected_id if adjudication else None}[run.decision_source]
    chosen=next((h for h in (hs.target,*hs.alternatives,hs.null_hypothesis) if h.hypothesis_id==selected),None)
    if chosen is None or run.final_hypothesis_id!=selected or run.final_choice!=chosen.type:
        reject('DECISION_SOURCE：最终假设与决定来源不一致')
    if adjudication is None:
        expected='PRIMARY' if red.red_team.recommended_id==hs.selected_id else 'RED_TEAM'
        if run.decision_source!=expected: reject('DECISION_SOURCE：反方选择来源不一致')
    return run
