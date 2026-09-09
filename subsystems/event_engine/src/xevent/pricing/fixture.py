"""完全虚构市场/指数/商品；不是实际行情或交易日历。"""
import argparse
import json
from datetime import timedelta
from pathlib import Path
from ..research.fixture import prepare as research_prepare
from ..research.provider import MockModelProvider, mock_output
from ..ledger.contracts import RawObservation, EventSeed
from ..ledger.store import ref
from ..research.packet import vr
from .contracts import *
from .engine import PricingEngine


def prepare(db,configs):
    w=research_prepare(db,configs)
    # 用Phase2既有结构化变更规则产生R3；不手填研究新颖度或改上游实现。
    from ..states.engine import StateEngine
    from ..ontology.contracts import ImpactSpec
    from ..graph.fixture import request as graph_request
    for version,amount in ((2,'100'),(3,'200')):
        w['ledger'].ingest(RawObservation(source_ref=ref(w['source']),locator='fixture:p6',
            raw=json.dumps({'amount':amount}).encode(),
            first_seen_at=w['clock'](),collected_at=w['clock'](),content_version=str(version),change_type='EDIT',
            is_first_hand=True,claim_kind='FACT',structured_basis='SOURCE_STRUCTURED',structured_fields={'amount':amount}),
            EventSeed(event_id='P6_EVENT',title_zh='虚构铜供应公告',dna=w['seed'].dna))
    event=max((e for e in w['ledger'].history(as_of=w['clock'](),kind='EventVersion') if e.object_id=='P6_EVENT'),key=lambda e:e.version)
    state_engine=StateEngine(w['ledger']); state_policy=state_engine.policy()
    state=state_engine.evaluate(vr(event),vr(state_policy),request_key='p8-state',as_of=w['clock']())
    event=w['ledger'].get(state.event_ref.object_id,state.event_ref.version)
    impact=w['ontology_engine'].impact('P8_IMPACT',1,ImpactSpec(event_ref=vr(event),variable_type='PRICE',
        target_object='COPPER',direction='UP',geography='GLOBAL',observation_kind='HYPOTHESIS',
        premise_refs=list(event.evidence_refs),mechanism_zh='虚构供应变化可能影响价格',uncertainty_zh='待研究验证'))
    resolution=w['ontology_engine'].resolve(vr(impact),vr(w['ontology']),as_of=w['clock'](),request_key='p8-resolution')
    history=w['graph'].build('P8_GRAPH',1,graph_request(w,event_ref=vr(event),resolution_refs=[vr(resolution)],
        exposure_refs=[vr(w['ex']),vr(w['negative'])]))
    packet=w['research'].packet('P8_PACKET',vr(history),vr(w['model']),as_of=w['clock']())
    w.update(event=event,state=state,impact=impact,resolution=resolution,history=history,packet=packet)
    def response(role,data):
        out=mock_output(role,data)
        if role=='PRIMARY': out['target']['confidence_band']='HIGH'
        return out
    analysis=w['research'].run('P8_RESEARCH',vr(w['packet']),MockModelProvider(response))
    engine=PricingEngine(w['ledger']); w.update(pricing=engine,analysis=analysis)
    path=w['ledger'].get(w['packet'].positive_path_refs[0].object_id,1)
    security=w['ledger'].get(path.security_ref.object_id,path.security_ref.version)
    w.update(path=path,security=security)
    start=w['clock']().replace(microsecond=0)+timedelta(seconds=2)
    end=start+timedelta(minutes=30)
    w['clock'].value=end+timedelta(seconds=1)
    w.update(start=start,end=end,pre_start=w['event'].first_seen_at-timedelta(minutes=21),
             pre_end=w['event'].first_seen_at-timedelta(minutes=1))
    def pub(cls,identity,**fields):
        return engine.publish(cls,identity,dict(observed_at=w['clock']().isoformat(),
            provenance_zh='完全虚构工程数据；无真实覆盖或Alpha声明',**fields),as_of=w['clock']())
    w['publish']=pub
    w['policy']=pub(PricingPolicy,'P8_POLICY',rules={})
    w['provider']=pub(ProviderQualification,'P8_PROVIDER',provider='fixture',source_ref=ref(w['source']),
        qualification_status='PROVIDER_QUALIFIED',timestamp_verified=True,unit_verified=True,currency_verified=True,
        qualification_evidence_zh='仅离线虚构协议的时钟单位测试，不代表真实provider资格')
    w['index']=pub(MarketInstrument,'P8_INDEX',canonical_name_zh='虚构大盘指数',asset_type='INDEX',currency='CNY',timezone='Asia/Shanghai')
    w['industry_index']=pub(MarketInstrument,'P8_INDUSTRY_INDEX',canonical_name_zh='虚构铜产业指数',asset_type='INDEX',currency='CNY',timezone='Asia/Shanghai')
    w['adjustments']={}; w['sessions']={}
    def setup_asset(asset):
        stamp=end.replace(hour=0,minute=0,second=0,microsecond=0)
        windows=[dict(start=(stamp+timedelta(days=i)).isoformat(),end=(stamp+timedelta(days=i+1)).isoformat()) for i in range(-10,5)]
        w['adjustments'][asset.object_id]=pub(AdjustmentBasis,'ADJ_'+asset.object_id,instrument_ref=ref(asset),
            adjustment_type='UNADJUSTED',factor=1.0,source_ref=ref(w['source']))
        w['sessions'][asset.object_id]=pub(MarketSession,'SESSION_'+asset.object_id,instrument_ref=ref(asset),
            source_ref=ref(w['source']),timezone='Asia/Shanghai',utc_offset_minutes=480,intervals=windows,calendar_version='FICTIONAL_CONTINUOUS_SESSION_V1')
    w['setup_asset']=setup_asset
    for asset in (security,w['index'],w['industry_index']): setup_asset(asset)
    for role,asset in (('MARKET',w['index']),('INDUSTRY',w['industry_index'])):
        w[role+'_composition']=pub(BenchmarkComposition,'COMP_'+role,benchmark_ref=ref(asset),
            component_security_refs=[ref(security)],expected_component_count=1,source_ref=ref(w['source']),
            industry_ref=ref(w['ex'].industry_ref) if role=='INDUSTRY' else None,coverage_status='COMPLETE_DECLARED_SCOPE')
    raw='虚构研究核验：传播已确认；后续披露尚未发布；待新增披露公开；若披露取消则假设失效；已逐项排查替代解释和不反应原因，仅代表工程设定。'
    ev=w['ledger'].ingest(RawObservation(source_ref=ref(w['source']),locator='fixture:p8-review',raw=raw.encode(),
        first_seen_at=w['clock'](),collected_at=w['clock'](),content_version='1',claim_kind='FACT',is_first_hand=True),
        EventSeed(event_id='P8_REVIEW_ARCHIVE',title_zh='虚构定价观察核验',dna=w['seed'].dna))
    w['review_evidence']=ev
    findings=[dict(dimension=c,outcome='NO',evidence_ref=ref(ev),quoted_span=raw,
        interpretation_zh='虚构逐项排查未发现该解释，不宣称真实因果证明',reviewed_by='fixture审阅者') for c in dict.fromkeys((*CAUSES,*NONREACTION))]
    findings += [dict(dimension=c,outcome='YES',evidence_ref=ref(ev),quoted_span=raw,
        interpretation_zh='虚构传播和后续扩散假设待检验',reviewed_by='fixture审阅者') for c in ('DISSEMINATION','REMAINING_DIFFUSION')]
    w['context']=pub(PricingContext,'P8_CONTEXT',event_ref=ref(w['event']),security_ref=ref(security),findings=findings)
    return w


def observation(w,identity,instrument,kind,value,start,end=None,*,version=1,**changes):
    end=end or start
    seen=w['clock'](); received=w['clock']()
    unit={'PRICE':'INDEX_POINT' if isinstance(instrument,MarketInstrument) and instrument.asset_type=='INDEX' else 'CURRENCY_PER_UNIT',
        'VOLUME':'SHARE','AMOUNT':'CURRENCY','CROSS_ASSET':'FX_RATE' if isinstance(instrument,MarketInstrument) and instrument.asset_type=='FX' else 'CURRENCY_PER_UNIT'}.get(kind,'RATIO')
    data=dict(observed_at=end.isoformat(),provenance_zh='虚构市场观察，原始单位与窗口完整保留',
        instrument_ref=ref(instrument),observation_type=kind,window=dict(start=start.isoformat(),end=end.isoformat()),
        value=value,unit=unit,currency=instrument.currency if kind in ('PRICE','CROSS_ASSET','AMOUNT','VWAP') else None,
        adjustment_ref=ref(w['adjustments'][instrument.object_id]),adjustment_type='UNADJUSTED',
        source_ref=ref(w['source']),provider_ref=ref(w['provider']),provider='fixture',provider_timestamp=end.isoformat(),
        received_at=received.isoformat(),first_seen_at=seen.isoformat(),session_ref=ref(w['sessions'][instrument.object_id]),
        staleness_seconds=(received-end).total_seconds(),quality_status='QUALIFIED')
    return w['pricing'].publish(MarketObservation,identity,{**data,**changes},as_of=w['clock'](),version=version)


def request(w,*,stock_return=0.0,industry_return=0.0,market_return=0.0,pre_return=0.0,flow=1.0,prefix='DEMO',buyer=True):
    obs=[]
    def point(label,asset,value,stamp):
        o=observation(w,prefix+label,asset,'PRICE',value,stamp); obs.append(o); return o
    a=point(':START',w['security'],100.0,w['start']); b=point(':END',w['security'],100.0*(1+stock_return),w['end'])
    pre=[point(':PRE_START',w['security'],100.0,w['pre_start']),
         point(':PRE_END',w['security'],100.0*(1+pre_return),w['pre_end'])]
    benchmarks=[]
    for role,asset,value in (('MARKET',w['index'],market_return),('INDUSTRY',w['industry_index'],industry_return)):
        ps=[point(':'+role+':START',asset,100.0,w['start']),point(':'+role+':END',asset,100.0*(1+value),w['end'])]
        benchmarks.append(w['pricing'].benchmark(prefix+':BM:'+role,price_refs=[vr(o) for o in ps],
            composition_ref=vr(w[role+'_composition']),benchmark_role=role,as_of=w['clock']()))
    fields={}
    for kind,base in (('VOLUME',1000.0),('AMOUNT',100000.0)):
        current=observation(w,prefix+':'+kind,w['security'],kind,base*flow,w['start'],w['end'])
        olds=[observation(w,prefix+':'+kind+':BASE:'+str(i),w['security'],kind,base,
            w['start']-timedelta(days=i),w['end']-timedelta(days=i)) for i in (1,2,3)]
        fields[kind.lower()+'_ref']=vr(current); fields[kind.lower()+'_baseline_refs']=[vr(o) for o in olds]
    buyers=[]
    if buyer:
        buyers=[NextBuyerSpec(buyer_type='EARNINGS_REPRICING',supporting_observation_refs=[vr(b)],
            supporting_path_refs=[vr(w['path'])],why_not_already_present='后续披露尚未发布',
            expected_trigger='待新增披露公开',failure_condition='若披露取消则假设失效',
            confidence_band='MEDIUM',non_presence_evidence_ref=vr(w['review_evidence']),
            quoted_span='后续披露尚未发布；待新增披露公开；若披露取消则假设失效')]
    return PricingRequest(analysis_ref=vr(w['analysis']),security_ref=vr(w['security']),path_ref=vr(w['path']),
        policy_ref=vr(w['policy']),as_of=w['clock'](),pricing_mode='ENGINEERING_FIXTURE',
        reaction_window=Window(start=w['start'],end=w['end']),price_refs=[vr(a),vr(b)],pre_price_refs=[vr(o) for o in pre],
        benchmark_refs=[vr(o) for o in benchmarks],context_ref=vr(w['context']),next_buyers=buyers,
        diffusion_price_refs=[vr(a),vr(b)],**fields)


def main():
    parser=argparse.ArgumentParser(description='Phase8完全虚构市场定价研究；无真实行情或API')
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--configs',type=Path,default=Path('configs'))
    args=parser.parse_args()
    if args.db.exists(): raise ValueError('FIXTURE_DB：必须使用新隔离数据库')
    w=prepare(args.db,args.configs)
    try:
        result=w['pricing'].assess('P8_DEMO',request(w,stock_return=0.05,industry_return=0.05))
        print(json.dumps(w['pricing'].report(vr(result),as_of=w['clock'](),pricing_mode='ENGINEERING_FIXTURE'),ensure_ascii=False,indent=2))
    finally: w['ledger'].close()


if __name__=='__main__': main()