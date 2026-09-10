"""Fictional multi-event package generated through accepted Phase 2–8 APIs.

No handcrafted PricingAssessment, AnalysisRun, Graph or Candidate output is imported.
The same fictional company/security can have different grades for different mechanisms.
"""
import argparse
import json
from datetime import timedelta
from pathlib import Path
from ..pricing.fixture import prepare,request,observation
from ..pricing.contracts import PricingRequest,PricingContext
from ..ledger.contracts import RawObservation,EventSeed
from ..ledger.store import ref
from ..states.engine import StateEngine
from ..ontology.contracts import ImpactSpec
from ..graph.fixture import request as graph_request
from ..research.provider import MockModelProvider,mock_output
from ..research.packet import vr
from ..exposures.fixture import disclose,exposure,metric
from .contracts import RankRequest
from .engine import RankingEngine


def prepare_package(db,configs):
    w=prepare(db,configs)
    # Explicit fictional restatement; verified metrics must locate 80/100 and 20/100 in raw.
    disclosure=disclose(w,2,raw_text='虚构甲公司更正年报：拥有铜矿，收入80，总收入100，小业务收入20，铜产量20；人工核实归属及计量口径')
    w['ex']=w['master'].exposure(2,exposure(w,disclosure,effective_to=None))
    low=w['master'].exposure(1,exposure(w,disclosure,exposure_id='P9_SMALL_BUSINESS',effective_to=None,
        mechanism_zh='虚构小业务铜产出，单列已披露收入口径'))
    w['master'].metric(2,metric(w['ex'],numerator=80.0))
    w['master'].metric(1,metric(low,metric_id='P9_SMALL_REVENUE',numerator=20.0))
    w['negative']=w['master'].exposure(3,exposure(w,disclosure,exposure_id='EXP_INPUT',effective_to=None,
        industry_ref=dict(object_id='XIND_COPPER_USERS',version=1),business_role='INPUT_USER',
        mechanism_zh='虚构加工业务投入铜，保留潜在负向成本机制'))
    cases=('A1_A','A1_B','A2_A','A2_B','BETA','WATCH','OVERPRICED','NULL','INVALIDATED')
    state_engine=StateEngine(w['ledger']); state_policy=state_engine.policy()
    prepared=[]
    for label in cases:
        event_id='P9_EVENT_'+label
        for v,amount in ((1,'100'),(2,'200')):
            w['ledger'].ingest(RawObservation(source_ref=ref(w['source']),locator='fixture:p9:'+label,
                raw=json.dumps({'detail':label,'amount':amount}).encode(),first_seen_at=w['clock'](),collected_at=w['clock'](),
                content_version=str(v),change_type='INITIAL' if v==1 else 'EDIT',is_first_hand=True,claim_kind='FACT',
                structured_basis='SOURCE_STRUCTURED',structured_fields={'detail':label,'amount':amount}),
                EventSeed(event_id=event_id,title_zh='虚构独立事件 '+label,dna=w['seed'].dna))
        event=max(w['ledger'].history(kind='EventVersion',as_of=w['clock']()),key=lambda o:(o.object_id==event_id,o.version))
        state=state_engine.evaluate(vr(event),vr(state_policy),request_key=label,as_of=w['clock']())
        event=w['ledger'].get(state.event_ref.object_id,state.event_ref.version)
        impact=w['ontology_engine'].impact('P9_IMPACT_'+label,1,ImpactSpec(event_ref=vr(event),variable_type='PRICE',target_object='COPPER',
            direction='UP',geography='GLOBAL',observation_kind='HYPOTHESIS',premise_refs=event.evidence_refs,
            mechanism_zh='虚构供应变化可能影响铜价；保持正负路径',uncertainty_zh='需求与成本可能抵消'))
        resolution=w['ontology_engine'].resolve(vr(impact),vr(w['ontology']),as_of=w['clock'](),request_key=label)
        history=w['graph'].build('P9_GRAPH_'+label,1,graph_request(w,event_ref=vr(event),resolution_refs=[vr(resolution)],
            exposure_refs=[vr(w['ex']),vr(low),vr(w['negative'])]))
        packet=w['research'].packet('P9_PACKET_'+label,vr(history),vr(w['model']),as_of=w['clock']())
        paths=[w['ledger'].get(r.object_id,r.version) for r in packet.positive_path_refs]
        path=next(p for p in paths if p.exposure_ref==vr(low if label=='BETA' else w['ex']))
        def respond(role,data,label=label,path=path):
            if role=='PRIMARY':
                data={**data,'packet':{**data['packet'],'eligible_positive_paths':sorted(data['packet']['eligible_positive_paths'],key=lambda p:p['ref']!=ref(path))}}
            out=mock_output(role,data)
            if role=='PRIMARY':
                out['target']['confidence_band']='HIGH'
                if label=='NULL': out['selected_id']='NULL'
            if role=='RED_TEAM':
                out['verdict']='TARGET_INVALIDATED' if label=='INVALIDATED' else 'TARGET_WEAKENED' if label.startswith('A2') else 'UNCHANGED'
                out['recommended_id']='NULL' if label in ('NULL','INVALIDATED') else 'TARGET'
            return out
        analysis=w['research'].run('P9_RUN_'+label,vr(packet),MockModelProvider(respond))
        prepared.append(dict(label=label,event=event,path=path,history=history,analysis=analysis))
    # All market inputs are published before any assessment, avoiding stale-input fallback.
    market_start=w['clock']().replace(microsecond=0)+timedelta(seconds=2)
    market_end=market_start+timedelta(minutes=30)
    w['clock'].value=market_end+timedelta(days=3,seconds=30)
    requests=[]
    for i,case in enumerate(prepared):
        label=case['label']; local={**w,**case}
        local['start']=market_start+timedelta(days=3,seconds=i)
        local['end']=market_end+timedelta(days=3,seconds=i)
        # A unique exact window per event, with honest system-known anchors.
        findings=w['context'].findings
        local['context']=w['pricing'].publish(PricingContext,'P9_CONTEXT_'+label,
            dict(event_ref=ref(case['event']),security_ref=ref(w['security']),findings=[f.model_dump(mode='json') for f in findings],
                observed_at=w['clock']().isoformat(),provenance_zh='虚构逐项传播及替代原因核验'),as_of=w['clock']())
        stock=0.08 if label=='OVERPRICED' else 0.051 if label=='BETA' else 0.0
        industry=0.05 if label=='BETA' else 0.0
        req=request(local,prefix='P9_MARKET_'+label,stock_return=stock,industry_return=industry,
            flow=5.0 if label=='OVERPRICED' else 1.0,buyer=label not in ('WATCH','OVERPRICED'))
        fields={}
        # Pre-event same-clock baseline, not post-event daily totals.
        for kind,value in (('VOLUME',1000.0),('AMOUNT',100000.0)):
            fields[kind.lower()+'_baseline_refs']=[vr(observation(w,'P9_BASE_'+label+kind+str(day),w['security'],kind,value,
                market_start+timedelta(seconds=i)-timedelta(days=day),market_end+timedelta(seconds=i)-timedelta(days=day))) for day in (1,2,3)]
        if label=='OVERPRICED':
            fields['prior_session_price_refs']=[vr(observation(w,'P9_TREND_'+str(day)+part,w['security'],'PRICE',value,stamp+timedelta(days=day,seconds=i)))
                for day in (0,1,2) for part,value,stamp in (('A',100.0,market_start),('B',108.0,market_end))]
        requests.append(PricingRequest.model_validate({**req.model_dump(),**fields}))
    # request() emitted identical pre-event endpoints with distinct IDs; use the final fixed pair everywhere.
    # Same values are still a knowledge revision and must not bypass A1 scope freshness.
    final_pre=requests[-1].pre_price_refs
    pricing=[]
    for case,req in zip(prepared,requests):
        req=PricingRequest.model_validate({**req.model_dump(),'pre_price_refs':final_pre,'as_of':w['clock']()})
        pricing.append(w['pricing'].assess('P9_PRICING_'+case['label'],req))
    ranking=RankingEngine(w['ledger']); policy=ranking.policy()
    req=RankRequest(snapshot_ref=vr(w['snapshot']),history_refs=[vr(c['history']) for c in prepared],policy_ref=vr(policy),as_of=w['clock']())
    package=ranking.build('P9_DEMO',req)
    empty=ranking.build('P9_EMPTY',req.model_copy(update={'history_refs':(),'as_of':w['clock']()}))
    return w,ranking,package,empty,pricing


def main():
    parser=argparse.ArgumentParser(description='Phase9虚构多事件分榜；不代表真实Alpha或投资建议')
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--configs',type=Path,default=Path('configs'))
    args=parser.parse_args()
    if args.db.exists(): raise ValueError('FIXTURE_DB_NEW_ONLY')
    w,engine,package,empty,_=prepare_package(args.db,args.configs)
    try:
        print(json.dumps(dict(机会包=engine.report(vr(package),as_of=w['clock'](),ranking_mode=package.ranking_mode),
            空榜例=engine.report(vr(empty),as_of=w['clock'](),ranking_mode=empty.ranking_mode)),ensure_ascii=False,indent=2))
    finally: w['ledger'].close()


if __name__=='__main__': main()
