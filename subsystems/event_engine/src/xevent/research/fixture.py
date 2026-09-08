"""纯离线中文研究演示；现有Phase6 fixture不改动。"""
import argparse
import json
from pathlib import Path
from ..graph.fixture import prepare as graph_prepare, request
from ..states.engine import StateEngine
from ..ontology.contracts import ImpactSpec
from ..exposures.fixture import exposure, metric
from .packet import vr
from .engine import ResearchEngine
from .provider import MockModelProvider


def prepare(db, configs, *, mixed=False, **config):
    w=graph_prepare(db,configs)
    state_engine=StateEngine(w['ledger']); policy=state_engine.policy()
    state=state_engine.evaluate(vr(w['event']),vr(policy),request_key='p7-state',as_of=w['clock']())
    event=w['ledger'].get(state.event_ref.object_id,state.event_ref.version)
    impact=w['ontology_engine'].impact('P7_PRICE',1,ImpactSpec(event_ref=vr(event),variable_type='PRICE',target_object='COPPER',
        direction='UP',geography='GLOBAL',observation_kind='HYPOTHESIS',premise_refs=list(event.evidence_refs),
        mechanism_zh='供应变化可能影响产出价格，仍需核验',uncertainty_zh='需求库存及成本可能抵消'))
    resolution=w['ontology_engine'].resolve(vr(impact),vr(w['ontology']),as_of=w['clock'](),request_key='p7-resolution')
    negative=w['negative']
    if not mixed:
        d=w['ledger'].get(negative.source_disclosure_ref.object_id,negative.source_disclosure_ref.version)
        # 明确fixture业务角色不同，故不匹配投入方Candidate；不是删掉真实负向暴露。
        negative=w['master'].exposure(2,exposure(w,d,exposure_id=negative.object_id,effective_to=None,
            industry_ref=negative.industry_ref,business_role='SERVICE_PROVIDER'))
    m=w['master'].metric(1,metric(w['ex']))
    history=w['graph'].build('P7_GRAPH',1,request(w,event_ref=vr(event),resolution_refs=[vr(resolution)],
        exposure_refs=[vr(w['ex']),vr(negative)]))
    engine=ResearchEngine(w['ledger'])
    prompt,model=engine.configure(**config)
    packet=engine.packet('P7_PACKET',vr(history),vr(model),as_of=w['clock']())
    w.update(event=event,state=state,impact=impact,resolution=resolution,negative=negative,metric=m,
        history=history,research=engine,prompt=prompt,model=model,packet=packet)
    return w


def main():
    parser=argparse.ArgumentParser(description='Phase7固定证据、独立反方与NULL中文Mock演示')
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--configs',type=Path,default=Path('configs'))
    args=parser.parse_args()
    if args.db.exists(): raise ValueError('FIXTURE_DB：仅允许新隔离数据库')
    w=prepare(args.db,args.configs,mixed=True)
    try:
        result=w['research'].run('P7_DEMO',vr(w['packet']),MockModelProvider())
        print(json.dumps(w['research'].report(vr(result)),ensure_ascii=False,indent=2))
    finally:
        w['ledger'].close()


if __name__=='__main__': main()
