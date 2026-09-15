"""Bounded manual L1 collection, with the existing Phase 2 ledger as sole authority."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import Field, model_validator, TypeAdapter
from typing import Literal
from ..contracts.common import Contract, Items, Text, SHA256, UTCDateTime
from ..contracts.models import Source
from ..ledger.contracts import EventSeed
from ..ledger.store import Ledger, ref, digest
from ..adapters.http import HTTPAdapter, SourceUnavailable
from ..runtime.collector import collect_once

BASELINE = '453c08940eca12cab1d82086a8344acae34163ce'

class SourceReview(Contract):
    source_id: Text
    source_type: Literal['A_EXCHANGE_DISCLOSURE','B_CN_GOVERNMENT','C_OVERSEAS_REGULATOR']
    operator: Text
    locator: Text
    terms_status: Literal['REVIEWED','UNKNOWN','UNAVAILABLE']
    authorization_status: Literal['AUTHORIZED','NOT_REQUIRED','UNKNOWN','DENIED']
    allowed_uses: Items[Text]
    raw_retention_allowed: bool | None
    access_method: Literal['HTML','RSS']
    expected_timestamp_semantics: Text
    lifecycle_semantics: Text
    terms_locator: Text
    terms_sha256: SHA256
    terms_excerpt: Text
    reviewed_at: UTCDateTime
    authorization_basis: Text
    identity_verified: bool
    rss: bool
    min_bytes: int = Field(ge=1,le=1048576)
    required_marker: Text
    publication_policy: Literal['UNKNOWN']
    scope: Literal['PILOT01_NONCOMMERCIAL_LOCAL']
    registry_version: int = Field(ge=1)

    @model_validator(mode='after')
    def safe_config(self):
        for url in (self.locator,self.terms_locator):
            u=urlsplit(url)
            if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError('PUBLIC_HTTPS_LOCATOR_ONLY_NO_SECRETS')
        if self.rss!=(self.access_method=='RSS'): raise ValueError('ACCESS_METHOD_MISMATCH')
        if self.authorization_status in ('AUTHORIZED','NOT_REQUIRED'):
            if self.terms_status!='REVIEWED' or self.raw_retention_allowed is not True or not {'EVENT_RESEARCH','NONCOMMERCIAL_LOCAL_ONLY'}<=set(self.allowed_uses):
                raise ValueError('HOLD_SOURCE_AUTHORIZATION')
        return self

class Registry(Contract):
    pilot_id: Literal['L1_REAL_EVENT_PILOT01']
    sources: Items[SourceReview]

    @model_validator(mode='after')
    def unique(self):
        if len(self.sources)!=3 or len({s.source_id for s in self.sources})!=3 or len({s.source_type for s in self.sources})!=3:
            raise ValueError('PILOT_REQUIRES_THREE_DISTINCT_SOURCE_CLASSES')
        return self

class LandingAdapter(HTTPAdapter):
    """Only response validation and verified first-hand metadata; no new transport."""
    def __init__(self, review, **kwargs):
        super().__init__(**kwargs)
        self.review=review

    def fetch(self, source, **kwargs):
        result=super().fetch(source,**kwargs)
        if result.observation is not None:
            raw=result.observation.raw
            text=raw.decode('utf-8',errors='replace')
            if len(raw)<self.review.min_bytes or self.review.required_marker.casefold() not in text.casefold():
                raise SourceUnavailable('SOURCE_CONTENT_ANOMALY')
            if any(marker in text.casefold() for marker in ('captcha','access denied','verify you are human')):
                raise SourceUnavailable('SOURCE_CONTENT_ANOMALY')
            # Date-only HTML and multi-entry RSS cannot supply one exact published_at.
            # Existing response receipt times remain untouched.
            from dataclasses import replace
            observation=result.observation.model_copy(update={'is_first_hand':self.review.identity_verified})
            result=replace(result,observation=observation)
        return result

def runtime_root(path, repo_root):
    root=Path(path).resolve(); repo=Path(repo_root).resolve()
    if root==repo or root.is_relative_to(repo) or repo.is_relative_to(root):
        raise ValueError('RUNTIME_MUST_BE_OUTSIDE_REPOSITORY')
    if any((p/'.git').exists() for p in (root,*root.parents)):
        raise ValueError('RUNTIME_MUST_BE_OUTSIDE_REPOSITORY')
    for name in ('db','raw','logs','reports','state'):
        target=root/name
        if target.resolve()!=target: raise ValueError('RUNTIME_SYMLINK_FORBIDDEN')
        target.mkdir(parents=True,exist_ok=True)
    return root

def register(ledger, review):
    if review.reviewed_at>ledger.now(): raise ValueError('SOURCE_REVIEW_PIT')
    snapshot=review.model_dump(mode='json')
    review_hash=digest(snapshot)
    existing=[s for s in ledger.history(as_of=ledger.now(),kind='Source') if s.source_id==review.source_id]
    old=max(existing,key=lambda s:s.version,default=None)
    if old and old.version>review.registry_version: raise ValueError('SOURCE_REVIEW_RECOMPUTE_REQUIRED')
    if old and old.version==review.registry_version:
        if old.retention_policy!='LOCAL_NONCOMMERCIAL_ONLY; no raw redistribution; review='+review_hash: raise ValueError('SOURCE_REVIEW_VERSION_CONFLICT')
        return old
    if review.registry_version!=(old.version+1 if old else 1): raise ValueError('SOURCE_REVIEW_VERSION_ORDER')
    now=ledger.now()
    source=Source(object_id=review.source_id,source_id=review.source_id,version=review.registry_version,
        supersedes_version=old.version if old else None,recorded_at=now,available_at=now,
        run_id='L1_REGISTRATION',policy_version='L1:'+review_hash,content_hash='0'*64,
        name_zh=review.operator,platform=review.source_type,canonical_locator=review.locator,
        identity_status='VERIFIED' if review.identity_verified else 'UNVERIFIED',tier='S0',roles=('NARRATIVE',),
        access_method=review.access_method,retention_policy='LOCAL_NONCOMMERCIAL_ONLY; no raw redistribution; review='+review_hash,
        enabled=review.authorization_status in ('AUTHORIZED','NOT_REQUIRED'),terms_status=review.terms_status,
        authorization_status=review.authorization_status,allowed_uses=review.allowed_uses,raw_retention_allowed=review.raw_retention_allowed)
    return ledger.register_source(source)

def event_seed(review):
    return EventSeed(event_id='L1:'+review.source_id,title_zh='真实正式来源响应观察：'+review.operator,
        dna=dict(actor_refs=[],action_code='OBSERVE_OFFICIAL_DISCLOSURE',
            object_entities=[dict(entity_id=review.source_id,entity_type='OBJECT',name_zh=review.operator+'固定定位响应')],
            target_entities=[],domain_ids=['REAL_EVENT_SOURCE_PILOT'],geographic_scope=['CN' if review.source_type!='C_OVERSEAS_REGULATOR' else 'US'],
            temporal_scope='本地首次合法接收时点；非文章历史发布时点',identity_rule_version='L1_RESPONSE_SCOPE_V0.1'))

def collect_source(ledger,review,*,attempt_key,transport=None,sleep=None):
    source=register(ledger,review)
    with_adapter=LandingAdapter(review,transport=transport,clock=ledger.now,sleep=sleep,attempts=1)
    try:
        return collect_once(ledger,with_adapter,source,event_seed(review),attempt_key=attempt_key,rss=review.rss)
    finally: with_adapter.close()

def audit(ledger,registry,as_of=None):
    now=ledger.now(); at=TypeAdapter(UTCDateTime).validate_python(as_of) if as_of is not None else now
    if at>now: raise ValueError('AUDIT_FUTURE_CUTOFF')
    view=ledger.history(as_of=at); rows=[]; violations=0
    for review in registry.sources:
        sources=[s for s in view if isinstance(s,Source) and s.source_id==review.source_id]
        source=max(sources,key=lambda s:s.version) if sources else None
        evidences=[e for e in view if type(e).__name__=='EvidenceVersion' and e.source_ref.object_id==review.source_id]
        events=[e for e in view if type(e).__name__=='EventVersion' and e.object_id=='L1:'+review.source_id]
        novelty=[n for n in view if type(n).__name__=='NoveltyDecision' and n.evidence_ref.object_id in {e.object_id for e in evidences}]
        health=[h for h in view if type(h).__name__=='SourceHealth' and h.source_id==review.source_id]
        cursors=[c for c in view if type(c).__name__=='CollectorCursor' and c.source_id==review.source_id]
        raw_ids={e.raw_object_ref for e in evidences}
        raw_hashes={rid:hashlib.sha256(ledger.raw(rid)).hexdigest() for rid in sorted(raw_ids)}
        for e in evidences:
            if not e.first_seen_at<=e.collected_at<=e.recorded_at<=e.available_at: violations+=1
        rows.append(dict(source_id=review.source_id,source_type=source.platform if source else review.source_type,authorization=source.authorization_status if source else 'UNKNOWN',
            raw_count=len(raw_ids),evidence_count=len(evidences),origin_count=len({e.origin_cluster_id for e in evidences}),event_version_count=len(events),
            novelty=dict(Counter(n.classification for n in novelty)),raw_hashes=raw_hashes,
            health=max(health,key=lambda h:h.version).health if health else 'UNKNOWN',
            cursor_ref=ref(max(cursors,key=lambda c:c.version)) if cursors else None,
            timestamps=[dict(evidence_ref=ref(e),published_at=e.published_at,first_seen_at=e.first_seen_at,
                received_at=e.collected_at,recorded_at=e.recorded_at,available_at=e.available_at) for e in evidences]))
    return dict(pilot='L1_REAL_EVENT_PILOT01',as_of=at,accepted_baseline=BASELINE,python=sys.version.split()[0],platform=platform.platform(),
        sources=rows,pit_violation_count=violations,qualification='HOLD_REAL_EVENT_SOURCE_QUALIFICATION',
        reasons=['Three-class live qualification and lifecycle acceptance require explicit review; smoke is CURRENT_OBSERVATION_ONLY'],
        preserved_holds=['HOLD_REAL_A_SHARE_CALENDAR_QUALIFICATION','HOLD_MARKET_DATA_PROVIDER_LIVE','HOLD_MODEL_PROVIDER_LIVE','HOLD_REAL_FORWARD_QUALIFICATION'],
        api_budget=0,real_forward=False,phase11=False)

def main(argv=None):
    parser=argparse.ArgumentParser(description='L1真实事件：显式人工smoke；不启动后续研究或交易')
    parser.add_argument('command',choices=['smoke','audit','recover'])
    parser.add_argument('--registry',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--live-manual-smoke',action='store_true')
    parser.add_argument('--as-of',help='只读audit历史可知时点；不推进恢复')
    args=parser.parse_args(argv)
    if args.as_of and args.command!='audit': parser.error('--as-of only allowed for audit')
    repo=Path(__file__).resolve().parents[5]
    registry=Registry.model_validate_json(args.registry.read_text(encoding='utf-8'))
    if args.command=='smoke' and not args.live_manual_smoke: parser.error('LIVE_MANUAL_SMOKE explicit flag required')
    root=runtime_root(args.runtime,repo)
    if args.command!='smoke' and not (root/'db/events.sqlite').exists(): parser.error('existing ledger required')
    with closing(Ledger(root/'db/events.sqlite')) as ledger:
        if args.command=='recover': ledger.recover()
        if args.command=='smoke':
            # Keep the exact reviewed registry locally; no response bodies in Git or logs.
            snapshot=json.dumps(registry.model_dump(mode='json'),ensure_ascii=False,sort_keys=True)
            f=root/'state'/('registry-'+hashlib.sha256(snapshot.encode()).hexdigest()+'.json')
            if not f.exists(): f.write_text(snapshot,encoding='utf-8')
            for review in registry.sources:
                collect_source(ledger,review,attempt_key='L1:'+uuid4().hex)
        result=audit(ledger,registry,as_of=args.as_of)
        filename=root/'reports'/('report-'+uuid4().hex+'.json')
        filename.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    return 0

if __name__=='__main__': raise SystemExit(main())
