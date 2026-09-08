"""跨产业修订、同源确认与反证的图历史边界。"""
import pytest
from test_phase6_graph import w, build
from xevent.exposures.fixture import vr
from xevent.ledger.contracts import EventSeed, RawObservation
from xevent.ontology.contracts import ImpactSpec


@pytest.mark.pit
def test_later_industry_mapping_does_not_change_old_paths(w):
    from test_phase5_review import ontology_revision
    h,ps=build(w); cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    ontology=ontology_revision(w)
    resolution=w['ontology_engine'].resolve(vr(w['price']),vr(ontology),as_of=w['clock'](),request_key='new-ontology')
    _,new=build(w,'GRAPH',2,resolution_refs=[vr(resolution)])
    assert not new  # 固定产业v1暴露不得自动换成v2
    assert w['ledger'].replay(cutoff)==before
    assert all(any(r.object_id.startswith('XIND_') and r.version==1 for r in p.node_refs) for p in ps)


def other_event(w, name, *, origin=None, repeats=1):
    seed=EventSeed(event_id=name,title_zh='虚构同源或独立事件',dna=w['seed'].dna)
    for n in range(repeats):
        ev=w['ledger'].ingest(RawObservation(source_ref=vr(w['source']),locator=f'fixture:{name}:{n}',
            raw=f'虚构转述{name}第{n}次供应变动'.encode(),first_seen_at=w['clock'](),collected_at=w['clock'](),
            content_version='1',origin_ref=vr(origin) if origin else None,is_first_hand=not bool(origin),claim_kind='FACT'),seed)
    event=max((e for e in w['ledger'].history(as_of=w['clock'](),kind='EventVersion') if e.event_id==name),key=lambda e:e.version)
    impact=w['ontology_engine'].impact(name+'_PRICE',1,ImpactSpec(event_ref=vr(event),variable_type='PRICE',target_object='COPPER',
        direction='UP',geography='GLOBAL',observation_kind='HYPOTHESIS',premise_refs=[vr(ev)],
        mechanism_zh='供应可能影响铜价',uncertainty_zh='未核验价格反应'))
    resolution=w['ontology_engine'].resolve(vr(impact),vr(w['ontology']),as_of=w['clock'](),request_key=name+'-resolve')
    return event,resolution,ev


@pytest.mark.pit
def test_seventy_reposts_do_not_multiply_transmission(w):
    build(w)
    event,resolution,ev=other_event(w,'REPOST',origin=w['event_evidence'],repeats=70)
    h,ps=build(w,'REPOST_GRAPH',event_ref=vr(event),resolution_refs=[vr(resolution)])
    assert len(ps)==2
    assert w['ledger'].origin_summary(as_of=w['clock'](),event_id=event.object_id)['origin_count']==1
    groups=w['graph'].reverse('SEC_A',as_of=w['clock']())
    assert len(groups)==2  # 正/负分组；原历史保留，没有次数权重
    assert all(len(g['paths'])==2 for g in groups)


@pytest.mark.pit
def test_later_origin_confirmation_versions_without_backfill(w):
    h,ps=build(w)
    event,resolution,ev=other_event(w,'INDEPENDENT')
    build(w,'OTHER',event_ref=vr(event),resolution_refs=[vr(resolution)])
    cutoff=w['clock'](); before=w['ledger'].replay(cutoff)
    assert len(w['graph'].reverse('SEC_A',as_of=cutoff))==4
    first=w['event_evidence']
    span=f'{first.source_id} {first.canonical_url_or_locator} 与 {ev.source_id} {ev.canonical_url_or_locator} 同一原始消息'
    proof=w['ledger'].ingest(RawObservation(source_ref=vr(w['source']),locator='fixture:proof',raw=span.encode(),
        first_seen_at=w['clock'](),collected_at=w['clock'](),content_version='1',claim_kind='FACT'),
        EventSeed(event_id='PROOF',title_zh='虚构合源证明',dna=w['seed'].dna))
    w['ledger'].confirm_origin([first.origin_cluster_id,ev.origin_cluster_id],[vr(first),vr(ev)],
        confirmation_key='p6-confirm',confirmation_ref=vr(proof),proof_span=span)
    build(w,'GRAPH',2)
    build(w,'OTHER',2,event_ref=vr(event),resolution_refs=[vr(resolution)])
    assert len(w['graph'].reverse('SEC_A',as_of=w['clock']()))==2
    assert len(w['graph'].reverse('SEC_A',as_of=cutoff))==4
    assert w['ledger'].replay(cutoff)==before


@pytest.mark.pit
def test_later_counterevidence_filters_active_reverse_only_at_new_time(w):
    from xevent.states.engine import StateEngine
    build(w); cutoff=w['clock']()
    state=StateEngine(w['ledger']); policy=state.policy()
    assessment=state.assess(vr(w['event']),vr(w['event_evidence']),assessment_key='invalid',kind='INVALIDATION',
        quoted_span='明确宣布铜供应减少',reviewed_by='虚构核验者',interpretation_zh='虚构测试明确标注原始主张无效')
    result=state.evaluate(vr(w['event']),vr(policy),request_key='invalid',as_of=w['clock'](),assessment_refs=[vr(assessment)])
    assert result.fact_state=='INVALIDATED'
    assert w['graph'].reverse('SEC_A',as_of=w['clock']())==[]
    assert len(w['graph'].reverse('SEC_A',as_of=cutoff))==2
