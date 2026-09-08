"""完全虚构工程数据；不连接真实公司/行情或模型。"""
import argparse
import json
from pathlib import Path
from ..exposures.fixture import seed_fixture, disclose, exposure, add_security, vr
from ..ontology.contracts import ImpactSpec
from ..ontology.engine import OntologyEngine
from ..ledger.contracts import RawObservation, EventSeed
from ..ledger.store import ref
from .engine import TransmissionGraph
from .contracts import BuildRequest


def prepare(db, config_dir):
    w=seed_fixture(db,config_dir)
    add_security(w)
    d=disclose(w)
    # 纯fixture中业务区间开放，不把旧年度数据默认为当前持续。
    ex=w['master'].exposure(1,exposure(w,d,effective_to=None))
    negative=w['master'].exposure(1,exposure(w,d,exposure_id='EXP_INPUT',effective_to=None,
        industry_ref=dict(object_id='XIND_COPPER_USERS',version=1),business_role='INPUT_USER',
        mechanism_zh='虚构综合公司制造业务使用铜，投入成本可能增加'))
    seed=EventSeed(event_id='P6_EVENT',title_zh='虚构铜供应公告',dna=w['seed'].dna)
    ev=w['ledger'].ingest(RawObservation(source_ref=ref(w['source']),locator='fixture:p6',
        raw='虚构公告：明确宣布铜供应减少'.encode(),first_seen_at=w['clock'](),collected_at=w['clock'](),
        content_version='1',is_first_hand=True,claim_kind='FACT'),seed)
    event=w['ledger'].get('P6_EVENT',1)
    engine=OntologyEngine(w['ledger'])
    supply=engine.impact('P6_SUPPLY',1,ImpactSpec(event_ref=vr(event),variable_type='SUPPLY',target_object='COPPER',
        direction='DOWN',geography='GLOBAL',observation_kind='OBSERVED',evidence_refs=[vr(ev)],
        mechanism_zh='官方宣布供应减少，仅记录宣布',observation_basis=dict(evidence_ref=ref(ev),quoted_span='明确宣布铜供应减少',
            reviewed_by='虚构核验者',interpretation_zh='不推断已经执行',scope='ANNOUNCED_CHANGE')))
    price=engine.impact('P6_PRICE',1,ImpactSpec(event_ref=vr(event),variable_type='PRICE',target_object='COPPER',
        direction='UP',geography='GLOBAL',observation_kind='HYPOTHESIS',premise_refs=[vr(supply)],
        mechanism_zh='供应减少可能推高铜价',uncertainty_zh='需求和库存可能抵消，尚无价格观察'))
    resolution=engine.resolve(vr(price),vr(w['ontology']),as_of=w['clock'](),request_key='p6-resolve')
    snapshot=w['registry'].snapshot('P6_UNIVERSE',as_of=w['clock']())
    w.update(ex=ex,negative=negative,event=event,event_evidence=ev,supply=supply,price=price,resolution=resolution,snapshot=snapshot,
        graph=TransmissionGraph(w['ledger']),ontology_engine=engine)
    return w


def request(w, **changes):
    return BuildRequest.model_validate({**dict(event_ref=vr(w['event']),resolution_refs=[vr(w['resolution'])],
        exposure_refs=[vr(w['ex']),vr(w['negative'])],snapshot_ref=vr(w['snapshot']),as_of=w['clock']()),**changes})


def main():
    parser=argparse.ArgumentParser(description='Phase6 中文离线传导图工程演示')
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--configs',type=Path,default=Path('configs'))
    args=parser.parse_args()
    if args.db.exists():
        raise ValueError('FIXTURE_DB：只允许新隔离数据库')
    w=prepare(args.db,args.configs)
    try:
        history=w['graph'].build('P6_DEMO',1,request(w))
        paths=[w['ledger'].get(r.object_id,r.version) for r in history.path_refs]
        assessment=w['ledger'].get(history.assessment_refs[0].object_id,1)
        print(json.dumps(dict(说明='这是工程演示，不代表真实Alpha或投资建议。',公司净状态=assessment.net_effect_state,
            路径=[dict(方向=p.impact_direction,世界=p.world,暴露=p.exposure_type,经济层数=p.economic_depth,
                结果=p.mapping_state) for p in paths],HOLD=history.hold_reasons),ensure_ascii=False))
    finally:
        w['ledger'].close()


if __name__=='__main__':
    main()
