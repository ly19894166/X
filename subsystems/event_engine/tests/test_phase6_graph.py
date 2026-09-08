"""Phase6 离线领域与PIT回归；不修改旧测试。"""
from pathlib import Path
from datetime import timedelta
import json
import pytest
from pydantic import ValidationError
from xevent.graph.fixture import prepare, request
from xevent.graph.contracts import SCHEMAS, TransmissionPath, BuildRequest
from xevent.exposures.fixture import vr, exposure, disclose, security
from xevent.ontology.contracts import ImpactSpec
from xevent.ledger.store import ref, Ledger
from xevent.registry.contracts import RelationSpec

CONFIG=Path(__file__).parents[1]/'configs'


@pytest.fixture
def w(tmp_path):
    w=prepare(tmp_path/'p6.sqlite',CONFIG)
    yield w
    w['ledger'].close()


def build(w, identity='GRAPH', version=1, **changes):
    h=w['graph'].build(identity,version,request(w,**changes))
    return h,[w['ledger'].get(r.object_id,r.version) for r in h.path_refs]


def test_supply_price_and_positive_negative_mixed(w):
    h,ps=build(w)
    assert {p.impact_direction for p in ps}=={'POSITIVE','NEGATIVE'}
    assert all(p.mapping_state=='PLAUSIBLE' and p.economic_depth==3 for p in ps)
    assert all(p.exposure_type=='VERIFIED_DIRECT' for p in ps)
    assert w['supply'].observation_kind=='OBSERVED' and w['price'].observation_kind=='HYPOTHESIS'
    assert all(vr(w['supply']) in p.node_refs and vr(w['price']) in p.node_refs for p in ps)
    a=w['ledger'].get(h.assessment_refs[0].object_id,1)
    assert a.net_effect_state=='MIXED' and len(a.positive_path_refs)==len(a.negative_path_refs)==1
    assert a.strongest_counter_path_ref==a.negative_path_refs[0]
    for p in ps:
        edges=[w['ledger'].get(r.object_id,r.version) for r in p.edge_refs]
        assert all((e.from_ref,e.to_ref)==(p.node_refs[i],p.node_refs[i+1]) for i,e in enumerate(edges))


def test_name_or_empty_exposure_does_not_create_path(w):
    h,ps=build(w,exposure_refs=[])
    assert not ps and any('NO_ELIGIBLE_EXPOSURE' in s for s in h.hold_reasons)


@pytest.mark.parametrize('grade',['SUPPORTED_DIRECT','INFERRED','UNKNOWN','HOLD'])
def test_exposure_grade_preserved(w,grade):
    d=w['ledger'].get(w['ex'].source_disclosure_ref.object_id,1)
    ex=w['master'].exposure(1,exposure(w,d,exposure_id='LOW',effective_to=None,exposure_type=grade,validation_status='UNREVIEWED'))
    h,ps=build(w,exposure_refs=[vr(ex)])
    assert len(ps)==1 and ps[0].exposure_type==grade and ps[0].mapping_state=='PLAUSIBLE'
    assert (ps[0].research_status=='HOLD')==(grade in ('UNKNOWN','HOLD'))


@pytest.mark.parametrize('method',['VERIFIED_RULE','EXACT_ALIAS_REVIEWED'])
def test_phase5_gate_not_reopened(w,method):
    d=w['ledger'].get(w['ex'].source_disclosure_ref.object_id,1)
    with pytest.raises(ValidationError): exposure(w,d,mapping_method=method)


def test_role_mismatch_cannot_reverse_economic_meaning(w):
    d=w['ledger'].get(w['ex'].source_disclosure_ref.object_id,1)
    ex=w['master'].exposure(1,exposure(w,d,exposure_id='WRONG_ROLE',business_role='INPUT_USER',effective_to=None))
    h,ps=build(w,exposure_refs=[vr(ex)])
    assert ps==[] and any('ROLE_MISMATCH' in x for x in h.hold_reasons)


def test_narrative_path_uses_normalized_association_only(w):
    theme=w['ontology_engine'].theme('P6_THEME',1,event_ref=vr(w['event']),canonical_name_zh='虚构铜概念',
        description_zh='虚构市场主题，不证明公司业务',evidence_refs=[vr(w['event_evidence'])])
    d=w['ledger'].get(w['ex'].source_disclosure_ref.object_id,1)
    d=disclose(w,2,raw_text='虚构甲公司被媒体关联虚构铜概念；仅为市场叙事')
    from xevent.exposures.contracts import DisclosureSpec
    data={k:v for k,v in d.model_dump(mode='json').items() if k in DisclosureSpec.model_fields}
    data.update(disclosure_id='NARRATIVE_DISC',disclosure_type='NARRATIVE')
    d=w['master'].disclosure(1,DisclosureSpec.model_validate(data))
    ex=w['master'].exposure(1,exposure(w,d,exposure_id='NARRATIVE',industry_ref=None,narrative_theme_ref=vr(theme),
        exposure_type='NARRATIVE_ASSOCIATION',validation_status='UNREVIEWED',effective_to=None))
    h,ps=build(w,exposure_refs=[vr(ex)],resolution_refs=[])
    assert len(ps)==1 and ps[0].world=='NARRATIVE' and ps[0].benefit_level=='N1_NARRATIVE'
    assert ps[0].mapping_state=='NARRATIVE_ONLY' and ps[0].economic_depth==0
    assert w['ledger'].get(h.assessment_refs[0].object_id,1).net_effect_state=='UNKNOWN'


@pytest.mark.parametrize('field',['event_ref','snapshot_ref','resolution_refs','exposure_refs'])
def test_missing_fixed_refs_fail_closed(w,field):
    bad=dict(object_id='MISSING',version=1)
    with pytest.raises(ValueError): build(w,**{field:[bad] if field.endswith('refs') else bad})
    assert w['ledger'].history(as_of=w['clock'](),kind='MappingHistory')==[]


@pytest.mark.parametrize('mutation',['cycle','edge_count','endpoint','world'])
def test_path_machine_gate(w,mutation):
    _,ps=build(w)
    data=ps[0].model_dump(mode='json')
    if mutation=='cycle': data['node_refs'][2]=data['node_refs'][1]
    if mutation=='edge_count': data['graph_hop_count']=0
    if mutation=='endpoint': data['company_ref']=data['event_ref']
    if mutation=='world': data['world']='NARRATIVE'
    with pytest.raises(ValidationError): TransmissionPath.model_validate(data)


def test_schema_and_roundtrip(w):
    h,ps=build(w)
    for name,cls in SCHEMAS.items():
        assert cls.model_json_schema()['title']==name
        for obj in w['ledger'].history(as_of=w['clock'](),kind=name):
            assert cls.model_validate_json(obj.model_dump_json())==obj


def test_deep_explicit_premise_soft_degraded(w):
    parent=w['price']
    for n in range(2):
        data={k:v for k,v in parent.model_dump(mode='json').items() if k in ImpactSpec.model_fields}
        data['premise_refs']=[ref(parent)]
        parent=w['ontology_engine'].impact('DEEP'+str(n),1,ImpactSpec.model_validate(data))
    resolution=w['ontology_engine'].resolve(vr(parent),vr(w['ontology']),as_of=w['clock'](),request_key='deep')
    _,ps=build(w,resolution_refs=[vr(resolution)])
    assert len(ps)==2 and all(p.economic_depth==5 and p.research_status=='DEGRADED' for p in ps)
    assert all('ECONOMIC_DEPTH_REVIEW_REQUIRED' in p.reason_codes for p in ps)


@pytest.mark.pit
def test_every_original_input_obeys_cutoff_and_commit(w):
    req=request(w); h=w['graph'].build('GRAPH',1,req)
    assert h.available_at>req.as_of
    assert w['ledger'].history(as_of=req.as_of,kind='MappingHistory')==[]
    for r in h.path_refs:
        p=w['ledger'].get(r.object_id,r.version)
        for er in p.edge_refs:
            edge=w['ledger'].get(er.object_id,er.version)
            assert all(i.available_at<=req.as_of for i in edge.input_version_refs)
        assert p.available_at>=max(i.available_at for i in p.input_version_refs)
        forged=p.model_dump(mode='json')
        for r in forged['input_version_refs']:
            if r['object_id']==p.event_ref.object_id:
                r['available_at']=(p.as_of+timedelta(microseconds=1)).isoformat()
        with pytest.raises(ValidationError,match='GRAPH_PIT'):
            TransmissionPath.model_validate(forged)


@pytest.mark.pit
@pytest.mark.parametrize('point',['event','resolution','ex','snapshot'])
def test_later_node_cannot_enter_early_asof(w,point):
    with pytest.raises(ValueError): build(w,as_of=w[point].available_at-timedelta(microseconds=1))


@pytest.mark.pit
def test_exposure_correction_append_and_old_replay(w):
    h,ps=build(w); old=w['clock'](); before=w['ledger'].replay(old)
    d=w['ledger'].get(w['ex'].source_disclosure_ref.object_id,1)
    ex=w['master'].exposure(2,exposure(w,d,effective_to=None,exposure_type='INFERRED',validation_status='UNREVIEWED'))
    assert all('EXPOSURE_RECOMPUTE_REQUIRED' in g['recompute_reasons'] for g in w['graph'].reverse('SEC_A',as_of=w['clock']()) if any(p.exposure_ref.object_id==ex.object_id for p in g['paths']))
    with pytest.raises(ValueError,match='STALE'): build(w,'GRAPH',2)
    h2,ps2=build(w,'GRAPH',2,exposure_refs=[vr(ex),vr(w['negative'])])
    assert w['ledger'].replay(old)==before
    assert h2.previous_history_ref==vr(h)
    assert any(p.exposure_type=='INFERRED' for p in ps2)
    assert all(p.exposure_type=='VERIFIED_DIRECT' for p in ps)


@pytest.mark.pit
@pytest.mark.parametrize('change',['rename','delist'])
def test_security_revision_never_changes_old_path(w,change):
    h,ps=build(w); old=w['clock'](); before=w['ledger'].replay(old)
    fields={'security_name':'虚构新名称'} if change=='rename' else {'listing_status':'DELISTED','delisting_date':'2025-01-01'}
    s=w['registry'].security(2,security(w,**fields))
    h2,p2=build(w,'GRAPH',2)
    assert p2==[] and any('SNAPSHOT_REFRESH' in r for r in h2.hold_reasons)
    assert w['ledger'].replay(old)==before
    w['registry'].relation(2,RelationSpec(**w['proof'],relation_id='REL_SEC_A',company_ref=s.company_ref,security_ref=vr(s),
        identity_status='VERIFIED',identity_reason_zh='虚构归属核验'))
    snap=w['registry'].snapshot('NEW_SNAPSHOT',as_of=w['clock']())
    h3,p3=build(w,'GRAPH',3,snapshot_ref=vr(snap))
    assert (len(p3)==2)==(change=='rename')
    if p3: assert p3[0].security_ref.version==2


@pytest.mark.pit
def test_deterministic_replay_and_idempotent_request(w):
    req=request(w); h=w['graph'].build('GRAPH',1,req)
    before=w['ledger'].replay(w['clock']())
    assert w['graph'].build('GRAPH',1,req)==h
    assert w['ledger'].replay(w['clock']())==before
    assert w['ledger'].replay(w['clock']())==w['ledger'].replay(w['clock']())


def test_atomic_graph_rollback(w):
    before=w['ledger'].replay(w['clock']())
    def fault(stage):
        if stage=='after_transmission_graph': raise RuntimeError('injected')
    w['ledger'].fault=fault
    with pytest.raises(RuntimeError): build(w)
    w['ledger'].fault=lambda _:None
    assert w['ledger'].replay(w['clock']())==before
    assert len(build(w)[1])==2


def test_dangling_edge_or_node_rolls_back(w,monkeypatch):
    original=w['ledger']._put
    def put(conn,batch,kind,identity,version,payload,inputs=()):
        if kind=='EdgeVersion': inputs=[*inputs,dict(object_id='DANGLING',version=1)]
        return original(conn,batch,kind,identity,version,payload,inputs)
    monkeypatch.setattr(w['ledger'],'_put',put)
    with pytest.raises(ValueError,match='REFERENCE_INVALID'): build(w)


def test_reverse_and_alternative_are_read_only(w):
    build(w); before=w['ledger'].replay(w['clock']())
    groups=w['graph'].reverse('SEC_A',as_of=w['clock']())
    assert len(groups)==2 and sum(len(g['paths']) for g in groups)==2
    assert w['graph'].reverse('UNKNOWN',as_of=w['clock']())==[]
    assert len(w['graph'].alternatives('OTHER_COMPANY',industry_ref=w['ex'].industry_ref,as_of=w['clock']()))==1
    assert w['ledger'].replay(w['clock']())==before


def test_duplicate_input_rejected(w):
    with pytest.raises(ValidationError): request(w,exposure_refs=[vr(w['ex']),vr(w['ex'])])


@pytest.mark.pit
def test_event_state_and_market_records_untouched(w):
    before=w['ledger'].history(as_of=w['clock'](),kind='EventVersion')
    build(w)
    assert w['ledger'].history(as_of=w['clock'](),kind='EventVersion')==before


@pytest.mark.pit
def test_historical_exposure_kept_with_continuity_hold(w):
    d=w['ledger'].get(w['ex'].source_disclosure_ref.object_id,1)
    x=w['master'].exposure(2,exposure(w,d,effective_to='2025-01-02T00:00:00Z'))
    w['clock'].advance(days=2)
    h,ps=build(w,exposure_refs=[vr(x)])
    assert len(ps)==1 and ps[0].research_status=='HOLD'
    assert 'HISTORICAL_EXPOSURE_CONTINUITY_UNVERIFIED' in ps[0].reason_codes


def test_edge_evidence_is_scoped_to_its_mechanism(w):
    _,ps=build(w)
    for p in ps:
        first=w['ledger'].get(p.edge_refs[0].object_id,1)
        assert first.evidence_refs==(vr(w['event_evidence']),)
        last=w['ledger'].get(p.edge_refs[-1].object_id,1)
        assert vr(w['event_evidence']) not in last.evidence_refs


def test_unproved_narrative_association_holds(w):
    theme=w['ontology_engine'].theme('UNPROVED',1,event_ref=vr(w['event']),canonical_name_zh='没有证据的概念',
        description_zh='无公司关联原文',evidence_refs=[vr(w['event_evidence'])])
    d=w['ledger'].get(w['ex'].source_disclosure_ref.object_id,1)
    ex=w['master'].exposure(1,exposure(w,d,exposure_id='UNPROVED_EX',industry_ref=None,narrative_theme_ref=vr(theme),
        exposure_type='NARRATIVE_ASSOCIATION',validation_status='UNREVIEWED'))
    h,ps=build(w,exposure_refs=[vr(ex)],resolution_refs=[])
    assert not ps and any('NARRATIVE_ASSOCIATION_PROOF_REQUIRED' in r for r in h.hold_reasons)
