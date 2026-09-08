"""PR22 A1：新增回归，原466测试不改动。"""
import pytest
from pydantic import ValidationError
from test_phase6_graph import w, build
from test_phase6_history import other_event
from xevent.exposures.fixture import vr,exposure,add_security
from xevent.exposures.contracts import DisclosureSpec
from xevent.graph.fixture import request
from xevent.graph.contracts import ExposureSelectionManifest
from xevent.ontology.contracts import ImpactSpec
from xevent.ledger.store import ref,digest
from xevent.ledger.contracts import RawObservation,EventSeed
from xevent.registry.contracts import CompanySpec,RelationSpec
from xevent.states.engine import StateEngine


def revise(w,obj,**changes):
    """离线版本fixture：用于Phase4暂未开放修订入口的Candidate/Resolution契约。"""
    omitted={'object_id','version','recorded_at','computed_at','available_at','input_version_refs','content_hash','run_id','supersedes_version'}
    payload={k:v for k,v in obj.model_dump(mode='json').items() if k not in omitted}
    payload.update(changes)
    payload['supersedes_version']=obj.version
    inputs=[ref(r) for r in obj.input_version_refs]+[ref(obj)]
    w['ledger']._write('A1_FIXTURE:'+obj.object_id+str(obj.version+1),digest(payload),
        lambda conn,view,batch:w['ledger']._put(conn,batch,type(obj).__name__,obj.object_id,obj.version+1,payload,inputs))
    return w['ledger'].get(obj.object_id,obj.version+1)


def reasons(w,at=None):
    return {r for g in w['graph'].reverse('SEC_A',as_of=at or w['clock'](),active_only=False) for r in g['recompute_reasons']}


@pytest.mark.pit
@pytest.mark.parametrize('target,reason',[('price','IMPACT_RECOMPUTE_REQUIRED'),('supply','IMPACT_RECOMPUTE_REQUIRED'),
    ('resolution','RESOLUTION_RECOMPUTE_REQUIRED'),('candidate','CANDIDATE_RECOMPUTE_REQUIRED')])
def test_current_research_chain_gate_and_old_pit(w,target,reason):
    req=request(w); old=w['graph'].build('GRAPH',1,req); cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    obj=w['ledger'].get(w['resolution'].candidate_refs[0].object_id,1) if target=='candidate' else w[target]
    revise(w,obj)
    assert reason in reasons(w)
    assert reason not in reasons(w,cutoff)
    h,paths=build(w,'NEW')
    assert not paths and h.research_status=='HOLD' and reason in h.hold_reasons
    historical=w['graph'].build('PAST_REQUEST',1,req)
    assert len(historical.path_refs)==2
    assert w['ledger'].replay(cutoff)==before


@pytest.mark.pit
def test_new_resolution_and_candidate_ids_are_same_research_context(w):
    build(w); cutoff=w['clock']()
    newer=w['ontology_engine'].resolve(vr(w['price']),vr(w['ontology']),as_of=w['clock'](),request_key='a1-new-run')
    h,ps=build(w,'STALE')
    assert not ps and {'RESOLUTION_RECOMPUTE_REQUIRED','CANDIDATE_RECOMPUTE_REQUIRED'}<=set(h.hold_reasons)
    assert not reasons(w,cutoff)
    assert len(build(w,'FRESH',resolution_refs=[vr(newer)])[1])==2


def research(w,event,name):
    impact=w['ontology_engine'].impact(name,1,ImpactSpec(event_ref=vr(event),variable_type='PRICE',target_object='COPPER',
        direction='UP',geography='GLOBAL',observation_kind='HYPOTHESIS',premise_refs=list(event.evidence_refs),
        mechanism_zh='虚构供需传导假设',uncertainty_zh='待独立核验'))
    return w['ontology_engine'].resolve(vr(impact),vr(w['ontology']),as_of=w['clock'](),request_key=name)


@pytest.mark.pit
def test_state_of_old_event_cannot_be_applied_to_new_event(w):
    se=StateEngine(w['ledger']); policy=se.policy()
    st=se.evaluate(vr(w['event']),vr(policy),request_key='a1-state',as_of=w['clock']())
    event=w['ledger'].get(st.event_ref.object_id,st.event_ref.version)
    resolution=research(w,event,'STATE_KNOWN')
    _,old_paths=build(w,'KNOWN_STATE',event_ref=vr(event),resolution_refs=[vr(resolution)])
    cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    evidence=w['ledger'].ingest(RawObservation(source_ref=vr(w['source']),locator='fixture:a1-event-update',
        raw='虚构新增事件细节'.encode(),first_seen_at=w['clock'](),collected_at=w['clock'](),content_version='1',claim_kind='FACT'),
        EventSeed(event_id=event.object_id,title_zh=event.title_zh,dna=event.dna))
    new_event=max((e for e in w['ledger'].history(as_of=w['clock'](),kind='EventVersion') if e.object_id==event.object_id),key=lambda e:e.version)
    new_resolution=research(w,new_event,'STATE_PENDING')
    h,ps=build(w,'NEW_EVENT',event_ref=vr(new_event),resolution_refs=[vr(new_resolution)])
    assert h.research_status=='HOLD' and 'EVENT_STATE_RECOMPUTE_REQUIRED' in h.hold_reasons
    assert ps and all(p.state_ref is None and p.research_status=='HOLD' and 'EVENT_STATE_RECOMPUTE_REQUIRED' in p.reason_codes for p in ps)
    assert all(p.state_ref==vr(st) for p in old_paths)
    assert w['ledger'].replay(cutoff)==before


@pytest.mark.pit
def test_contradicted_state_marks_old_plausible_path_stale(w):
    h,ps=build(w); cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    se=StateEngine(w['ledger']); policy=se.policy()
    assessment=se.assess(vr(w['event']),vr(w['event_evidence']),assessment_key='a1-counter',kind='COUNTEREVIDENCE',
        quoted_span='明确宣布铜供应减少',reviewed_by='虚构人工核验者',interpretation_zh='虚构测试反证评估')
    state=se.evaluate(vr(w['event']),vr(policy),request_key='a1-counter',as_of=w['clock'](),assessment_refs=[vr(assessment)])
    assert state.fact_state=='CONTRADICTED'
    assert 'EVENT_STATE_RECOMPUTE_REQUIRED' in reasons(w)
    assert all(p.mapping_state=='PLAUSIBLE' for g in w['graph'].reverse('SEC_A',as_of=w['clock']()) for p in g['paths'])
    assert 'EVENT_STATE_RECOMPUTE_REQUIRED' not in reasons(w,cutoff)
    assert w['ledger'].replay(cutoff)==before


@pytest.mark.pit
@pytest.mark.parametrize('target,reason',[('company','COMPANY_RECOMPUTE_REQUIRED'),('relation','RELATION_RECOMPUTE_REQUIRED'),
    ('snapshot','SNAPSHOT_RECOMPUTE_REQUIRED')])
def test_identity_relation_snapshot_freshness(w,target,reason):
    build(w); cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    if target=='snapshot': w['registry'].snapshot('LATEST_UNIVERSE',as_of=w['clock']())
    elif target=='company':
        data={k:v for k,v in w['company'].model_dump(mode='json').items() if k in CompanySpec.model_fields}
        data['canonical_name_zh']='虚构新公司名称'
        w['registry'].company(2,CompanySpec.model_validate(data))
    else:
        old=w['ledger'].get('REL_SEC_A',1)
        data={k:v for k,v in old.model_dump(mode='json').items() if k in RelationSpec.model_fields}
        data['identity_reason_zh']='重新核实归属'
        w['registry'].relation(2,RelationSpec.model_validate(data))
    assert reason in reasons(w) and reason not in reasons(w,cutoff)
    assert w['ledger'].replay(cutoff)==before


def test_alternatives_cannot_cross_events_or_infer_ambiguous_scope(w):
    h,ps=build(w)
    event,res,ev=other_event(w,'UNRELATED_EVENT_B')
    build(w,'EVENT_B',event_ref=vr(event),resolution_refs=[vr(res)])
    kwargs=dict(industry_ref=w['ex'].industry_ref,as_of=w['clock']())
    with pytest.raises(ValueError,match='SCOPE_REQUIRED'): w['graph'].alternatives('OTHER',**kwargs)
    actual=w['graph'].alternatives('OTHER',event_ref=vr(w['event']),**kwargs)
    assert len(actual)==1 and all(p.event_ref==vr(w['event']) for p in actual)
    assert all(p.event_ref!=vr(event) for p in actual)
    assert w['graph'].alternatives('OTHER',history_ref=vr(h),candidate_ref=actual[0].candidate_ref,**kwargs)==actual


@pytest.mark.pit
def test_selection_manifest_exposes_omitted_negative_exposure(w):
    h,ps=build(w,exposure_refs=[vr(w['ex'])])
    m=w['ledger'].get(h.selection_manifest_ref.object_id,1)
    assert m.available_matching_exposure_count==2 and m.selected_exposure_refs==(vr(w['ex']),)
    assert m.excluded_exposure_refs==(vr(w['negative']),) and m.exclusions[0].reason_code=='OMITTED_BY_EXPLICIT_REQUEST_REVIEW_REQUIRED'
    assert m.selection_status=='HOLD_INCOMPLETE_SELECTION' and h.research_status=='HOLD'
    assert w['ledger'].get(h.assessment_refs[0].object_id,1).net_effect_state=='HOLD'
    assert ps[0].impact_direction=='POSITIVE'  # 原单路径保留，不冒充完整公司净结论
    assert 'EXPOSURE_SELECTION_REVIEW_REQUIRED' in reasons(w)
    assert w['graph'].alternatives('OTHER',event_ref=vr(w['event']),industry_ref=w['ex'].industry_ref,as_of=w['clock']())==[]
    assert ExposureSelectionManifest.model_validate_json(m.model_dump_json())==m


@pytest.mark.pit
def test_later_known_exposure_changes_selection_not_old_manifest(w):
    h,_=build(w); cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    d=w['ledger'].get(w['ex'].source_disclosure_ref.object_id,1)
    ex=w['master'].exposure(1,exposure(w,d,exposure_id='NEW_KNOWN_EXPOSURE',effective_to=None))
    assert 'EXPOSURE_SELECTION_RECOMPUTE_REQUIRED' in reasons(w)
    h2,_=build(w,'GRAPH',2)
    m=w['ledger'].get(h2.selection_manifest_ref.object_id,2)
    assert m.available_matching_exposure_count==3 and m.excluded_exposure_refs==(vr(ex),)
    assert w['ledger'].get(h.selection_manifest_ref.object_id,1).available_matching_exposure_count==2
    assert w['ledger'].replay(cutoff)==before


def test_manifest_complete_partition_cannot_be_forged(w):
    h,_=build(w); m=w['ledger'].get(h.selection_manifest_ref.object_id,1)
    assert m.selection_status=='COMPLETE_KNOWN_SUBSET'
    data=m.model_dump(mode='json'); data['selected_exposure_refs']=data['selected_exposure_refs'][:1]
    with pytest.raises(ValidationError): ExposureSelectionManifest.model_validate(data)


def test_alternatives_excludes_company_present_only_in_event_b(w):
    h,_=build(w)
    data={k:v for k,v in w['company'].model_dump(mode='json').items() if k in CompanySpec.model_fields}
    data.update(company_id='CO_B_ONLY',canonical_name_zh='虚构乙公司',legal_name='虚构乙有限公司',company_identifier='FIXTURE-B')
    company=w['registry'].company(1,CompanySpec.model_validate(data))
    wb={**w,'company':company}
    add_security(wb,'SEC_B_ONLY',security_code='000002',ticker='000002.SZ')
    original=w['ledger'].get(w['ex'].source_disclosure_ref.object_id,1)
    data={k:v for k,v in original.model_dump(mode='json').items() if k in DisclosureSpec.model_fields}
    data.update(disclosure_id='DISC_B_ONLY',company_ref=ref(company),review_status='UNREVIEWED',issuer_identity_verified=False)
    disclosure=w['master'].disclosure(1,DisclosureSpec.model_validate(data))
    ex=w['master'].exposure(1,exposure(wb,disclosure,exposure_id='EX_B_ONLY',effective_to=None,
        exposure_type='INFERRED',validation_status='UNREVIEWED'))
    snapshot=w['registry'].snapshot('B_UNIVERSE',as_of=w['clock']())
    event,res,_=other_event(w,'EVENT_B_ONLY')
    build(w,'B_ONLY',event_ref=vr(event),resolution_refs=[vr(res)],snapshot_ref=vr(snapshot),
        exposure_refs=[vr(w['ex']),vr(w['negative']),vr(ex)])
    kwargs=dict(industry_ref=ex.industry_ref,as_of=w['clock']())
    b=w['graph'].alternatives(w['company'].object_id,event_ref=vr(event),**kwargs)
    assert b and {p.company_ref.object_id for p in b}=={company.object_id}
    a=w['graph'].alternatives(w['company'].object_id,event_ref=vr(w['event']),**kwargs)
    assert all(p.company_ref.object_id!=company.object_id for p in a)
    assert all(w['ledger'].get(r.object_id,r.version).company_ref.object_id!=company.object_id for r in h.path_refs)
