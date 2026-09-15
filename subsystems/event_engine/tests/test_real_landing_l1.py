"""L1 additions only: fictional MockTransport responses, no live sockets."""
from dataclasses import replace
from pathlib import Path
import json
import hashlib
import httpx
import pytest
from pydantic import ValidationError
from test_phase2_ledger import Clock
from xevent.real_landing.pilot import Registry, SourceReview, register, collect_source, audit, runtime_root, event_seed, LandingAdapter
from xevent.ledger.store import Ledger,ref
from xevent.ledger.contracts import RawObservation
from xevent.runtime.collector import collect_once

@pytest.fixture
def registry():
    path=Path(__file__).resolve().parents[3]/'docs/real_landing/pilot01_sources.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    for i,s in enumerate(data['sources']):
        s.update(locator=f'https://source{i}.example/disclosure',terms_locator=f'https://source{i}.example/terms',
            operator=f'FICTIONAL_SOURCE_{i}',reviewed_at='2026-01-01T00:00:00Z',required_marker='FICTIONAL',min_bytes=5,
            rss=False,access_method='HTML')
    return Registry.model_validate(data)

@pytest.fixture
def world(tmp_path,registry):
    clock=Clock(); ledger=Ledger(tmp_path/'events.sqlite',clock=clock)
    yield ledger,clock,registry
    ledger.close()

def transport(content=b'FICTIONAL disclosure A'):
    return httpx.MockTransport(lambda request:httpx.Response(200,content=content))

@pytest.mark.pit
def test_complete_chain_duplicate_restart_and_old_cutoff(world):
    ledger,clock,registry=world; review=registry.sources[0]
    assert collect_source(ledger,review,attempt_key='first',transport=transport())['status']=='CURRENT_OBSERVATION_ONLY'
    cutoff=clock(); before=ledger.replay(cutoff)
    evidence=ledger.history(as_of=cutoff,kind='EvidenceVersion')[0]
    assert evidence.first_seen_at<=evidence.collected_at<=evidence.recorded_at<=evidence.available_at
    assert evidence.published_at is None and evidence.is_first_hand is True
    assert not ledger.history(as_of=evidence.first_seen_at,kind='EventVersion')
    assert hashlib.sha256(ledger.raw(evidence.raw_object_ref)).hexdigest()==evidence.raw_content_hash
    path=ledger.path; ledger.close(); other=Ledger(path,clock=clock)
    try:
        collect_source(other,review,attempt_key='restart',transport=transport())
        assert len(other.history(as_of=clock(),kind='EvidenceVersion'))==1
        assert len(other.history(as_of=clock(),kind='EventVersion'))==1
        assert {n.classification for n in other.history(as_of=clock(),kind='NoveltyDecision')}=={'R0','UNDETERMINED'}
        assert other.get(evidence.object_id,evidence.version)==evidence
        assert other.replay(cutoff)==before
        result=audit(other,registry)
        assert result['pit_violation_count']==0 and result['sources'][0]['raw_count']==1
        assert result['sources'][0]['health']=='OK' and result['sources'][0]['cursor_ref']
        assert other.history(as_of=clock(),kind='OriginClusterVersion')
        assert other.history(as_of=clock(),kind='OutboxJob')
    finally: other.close()

@pytest.mark.pit
def test_a_b_a_and_explicit_correction_retraction_append_only(world):
    ledger,clock,registry=world; review=registry.sources[0]
    for i,raw in enumerate((b'FICTIONAL A',b'FICTIONAL B',b'FICTIONAL A')):
        collect_source(ledger,review,attempt_key=str(i),transport=transport(raw))
    cutoff=clock(); old=ledger.replay(cutoff)
    es=ledger.history(as_of=cutoff,kind='EvidenceVersion')
    assert len(es)==3 and [ledger.raw(e.raw_object_ref) for e in es]==[b'FICTIONAL A',b'FICTIONAL B',b'FICTIONAL A']
    source=register(ledger,review)
    for i,kind in enumerate(('EDIT','RETRACT','DELETE')):
        o=RawObservation(source_ref=ref(source),locator=review.locator,raw=('FICTIONAL explicit '+kind).encode(),
            first_seen_at=clock(),collected_at=clock(),content_version='explicit'+str(i),change_type=kind,is_first_hand=True)
        ledger.ingest(o,event_seed(review))
    assert len(ledger.history(as_of=clock(),kind='EvidenceVersion'))==6
    assert ledger.replay(cutoff)==old
    assert {'EDIT','RETRACT','DELETE'}<={e.change_type for e in ledger.history(as_of=clock(),kind='EvidenceChange')}

@pytest.mark.parametrize('status',[301,302,400,401,403,404,429,500,502,503,504])
def test_http_failure_isolates_source_and_preserves_commits(world,status):
    ledger,clock,registry=world; a,b,c=registry.sources
    collect_source(ledger,c,attempt_key='healthy',transport=transport())
    good=[h for h in ledger.history(as_of=clock(),kind='SourceHealth') if h.source_id==c.source_id]
    calls=[]
    def failure(r): calls.append(r); return httpx.Response(status,headers={'Retry-After':'100','Location':'https://never.example/'})
    result=collect_source(ledger,a,attempt_key='failed',transport=httpx.MockTransport(failure))
    assert result['status']=='SOURCE_UNAVAILABLE' and len(calls)==1
    assert len(ledger.history(as_of=clock(),kind='EvidenceVersion'))==1
    assert [h for h in ledger.history(as_of=clock(),kind='SourceHealth') if h.source_id==c.source_id]==good
    assert not [e for e in ledger.history(as_of=clock(),kind='EvidenceChange') if e.change_type=='DELETE']

@pytest.mark.parametrize('exception',[httpx.ReadTimeout,httpx.ConnectError,httpx.RemoteProtocolError])
def test_network_failure_status(world,exception):
    ledger,clock,registry=world
    def fail(r): raise exception('FICTIONAL network failure',request=r)
    assert collect_source(ledger,registry.sources[0],attempt_key='failure',transport=httpx.MockTransport(fail))['status']=='SOURCE_UNAVAILABLE'
    assert ledger.history(as_of=clock(),kind='SourceHealth')[-1].health=='SOURCE_UNAVAILABLE'

@pytest.mark.parametrize('body',[b'',b'captcha FICTIONAL',b'wrong source content'])
def test_content_anomaly_not_ingested(world,body):
    ledger,clock,registry=world
    assert collect_source(ledger,registry.sources[0],attempt_key='bad',transport=transport(body))['status']=='SOURCE_UNAVAILABLE'
    assert not ledger.history(as_of=clock(),kind='EvidenceVersion')

def test_rss_parse_failure(world):
    ledger,clock,registry=world
    review=SourceReview.model_validate({**registry.sources[2].model_dump(), 'rss':True,'access_method':'RSS'})
    assert collect_source(ledger,review,attempt_key='parse',transport=transport())['status']=='SOURCE_UNAVAILABLE'

def test_unknown_authorization_never_requests(world):
    ledger,clock,registry=world
    calls=[]
    result=collect_source(ledger,registry.sources[1],attempt_key='hold',transport=httpx.MockTransport(lambda r:calls.append(r)))
    assert result['status']=='AUTHORIZATION_HOLD' and calls==[]
    assert ledger.history(as_of=clock(),kind='SourceHealth')[-1].health=='AUTHORIZATION_HOLD'

@pytest.mark.pit
def test_source_review_fixed_version_and_no_old_authorization_bypass(world):
    ledger,clock,registry=world; review=registry.sources[0]
    source=register(ledger,review)
    changed=SourceReview.model_validate({**review.model_dump(),'authorization_basis':'changed scope'})
    with pytest.raises(ValueError,match='VERSION_CONFLICT'):register(ledger,changed)
    newer=SourceReview.model_validate({**review.model_dump(),'registry_version':2,'authorization_status':'DENIED','raw_retention_allowed':False,'allowed_uses':[]})
    register(ledger,newer)
    with pytest.raises(ValueError,match='RECOMPUTE_REQUIRED'):register(ledger,review)
    assert ledger.get(source.object_id,1)==source

@pytest.mark.pit
@pytest.mark.parametrize('stage',['after_raw','after_evidence','before_commit','after_commit','before_receipt_commit','after_receipt_commit'])
def test_crash_recovery_reuses_phase2_no_partial_event(world,stage):
    ledger,clock,registry=world; review=registry.sources[0];register(ledger,review)
    def crash(at):
        if at==stage: raise RuntimeError('FICTIONAL crash')
    ledger.fault=crash
    with pytest.raises(RuntimeError):collect_source(ledger,review,attempt_key='crash',transport=transport())
    cutoff=clock(); assert not ledger.history(as_of=cutoff,kind='EventVersion')
    ledger.fault=lambda stage:None
    collect_source(ledger,review,attempt_key='recovered',transport=transport())
    assert len(ledger.history(as_of=clock(),kind='EventVersion'))==1
    assert len(ledger.history(as_of=clock(),kind='EvidenceVersion'))==1
    assert not ledger.history(as_of=cutoff,kind='EventVersion')

def test_cursor_failure_after_response_commit_recovers(world,monkeypatch):
    ledger,clock,registry=world; review=registry.sources[0]
    original=ledger.collector_result
    def fail(*args,**kwargs):raise RuntimeError('FICTIONAL cursor failure')
    monkeypatch.setattr(ledger,'collector_result',fail)
    with pytest.raises(RuntimeError):collect_source(ledger,review,attempt_key='cursorfail',transport=transport())
    assert len(ledger.history(as_of=clock(),kind='EvidenceVersion'))==1
    monkeypatch.setattr(ledger,'collector_result',original)
    collect_source(ledger,review,attempt_key='cursorretry',transport=transport())
    assert len(ledger.history(as_of=clock(),kind='EvidenceVersion'))==1
    assert ledger.history(as_of=clock(),kind='CollectorCursor')[-1].last_success_at

@pytest.mark.parametrize('url',['http://source.example/','https://token:secret@source.example/','https://source.example/?token=x','https://source.example/#secret'])
def test_source_locator_cannot_carry_credentials(registry,url):
    with pytest.raises(ValidationError):SourceReview.model_validate({**registry.sources[0].model_dump(),'locator':url})

def test_runtime_outside_repo(tmp_path):
    repo=tmp_path/'repo';repo.mkdir()
    with pytest.raises(ValueError,match='OUTSIDE'):runtime_root(repo/'runtime',repo)
    with pytest.raises(ValueError,match='OUTSIDE'):runtime_root(tmp_path,repo)
    root=runtime_root(tmp_path/'data',repo)
    assert {p.name for p in root.iterdir()}=={'db','raw','logs','reports','state'}

@pytest.mark.pit
def test_future_review_refused_before_request(world):
    ledger,clock,registry=world
    future=SourceReview.model_validate({**registry.sources[0].model_dump(),'reviewed_at':'2099-01-01T00:00:00Z'})
    with pytest.raises(ValueError,match='REVIEW_PIT'):collect_source(ledger,future,attempt_key='future',transport=transport())


@pytest.mark.pit
def test_historical_audit_does_not_use_later_source_authorization(world):
    ledger,clock,registry=world; review=registry.sources[0]
    collect_source(ledger,review,attempt_key='original',transport=transport())
    cutoff=clock(); before=audit(ledger,registry,as_of=cutoff)
    revised=SourceReview.model_validate({**review.model_dump(),'registry_version':2,'authorization_status':'DENIED','raw_retention_allowed':False,'allowed_uses':[]})
    register(ledger,revised)
    assert audit(ledger,registry,as_of=cutoff)==before
    assert audit(ledger,registry)['sources'][0]['authorization']=='DENIED'
    assert audit(ledger,registry,as_of='2026-01-01T00:00:00Z')['sources'][0]['raw_count']==0
    with pytest.raises(ValueError,match='FUTURE_CUTOFF'):audit(ledger,registry,as_of='2099-01-01T00:00:00Z')
