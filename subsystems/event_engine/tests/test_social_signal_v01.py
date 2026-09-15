"""Offline D pilot: invented posts only; the suite socket fence remains active."""
import json

import httpx
import pytest
from pydantic import ValidationError

from test_phase2_ledger import setup_ledger
from xevent.adapters.http import HTTPAdapter, SourceUnavailable
from xevent.contracts.models import Source
from xevent.ledger.store import Ledger, ref
from xevent.social.contracts import SocialContent, SocialObservation, SourceQualification
from xevent.social.pilot import collect_social, cursor_for, review_binding
from xevent.social.providers import normalize, endpoint_gate


ENDPOINTS = {
    "HN": "https://hacker-news.firebaseio.com/v0/item/123.json",
    "BLUESKY": "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=fixture&limit=1",
    "MASTODON": "https://social.example/api/v1/timelines/public?limit=1",
}


def body(platform, text="A"):
    if platform == "HN":
        return {"id": 123, "type": "story", "title": text, "by": "fixture-author", "time": 1000000000}
    if platform == "BLUESKY":
        return {"cursor": "page-fixture", "posts": [{"uri": "at://did:plc:fiction/app.bsky.feed.post/123",
            "author": {"did": "did:plc:fiction", "handle": "fiction.test"},
            "record": {"text": text, "createdAt": "2020-01-01T00:00:00Z"}}]}
    return [{"id": "123", "account": {"id": "7", "acct": "fiction"},
        "visibility": "public", "content": text, "created_at": "2020-01-01T00:00:00Z",
        "url": "https://social.example/@fiction/123"}]


def configure(ledger, clock, source, platform="HN", **review_changes):
    review = SourceQualification(source_name="ENGINEERING_FIXTURE", platform=platform,
        endpoint=ENDPOINTS[platform], official_api_doc="https://docs.example/fixture",
        authentication_required=False, rate_limit_status="OFFLINE", raw_retention_status="ALLOWED",
        redistribution_status="SYNTHETIC_ONLY", deletion_semantics="explicit provider state only",
        edit_semantics="append", reviewed_at=clock(), qualification_status="QUALIFIED",
        authorization_proof="invented fixture; not live authorization")
    review = SourceQualification.model_validate({**review.model_dump(), **review_changes})
    identity = "SOURCE_SOCIAL_" + platform
    source = ledger.register_source(Source.model_validate({**source.model_dump(),
        "object_id": identity, "source_id": identity, "version": 1, "supersedes_version": None,
        "platform": platform, "canonical_locator": review.endpoint, "enabled": True,
        "terms_status": "REVIEWED", "authorization_status": "AUTHORIZED",
        "allowed_uses": ["EVENT_RESEARCH"], "raw_retention_allowed": True,
        "retention_policy": review_binding(review)}))
    return source, review


def run(ledger, clock, source, review, seed, data, attempt="one", **kwargs):
    adapter = HTTPAdapter(transport=httpx.MockTransport(lambda r: httpx.Response(200,
        content=json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode())),
                          clock=clock, attempts=1)
    try:
        return collect_social(ledger, adapter, source, review, seed, attempt_key=attempt, **kwargs)
    finally:
        adapter.close()


@pytest.mark.parametrize("platform", ENDPOINTS)
def test_normalizers_nullable_counts(platform):
    rows, cursor = normalize(platform, json.dumps(body(platform)), instance="social.example")
    assert len(rows) == 1 and rows[0].like_count is None and rows[0].reply_count is None
    assert rows[0].signal_class == "SOCIAL_LEAD" and cursor


@pytest.mark.parametrize("changes", [
    {"signal_class": "CONFIRMED_FACT"}, {"signal_class": "OFFICIAL_SOCIAL_STATEMENT"},
    {"like_count": -1}, {"like_count": True}, {"created_at": "2020-01-01"},
    {"price_in": "LOW"}, {"rank": 1}, {"native_id": ""}])
def test_strict_social_schema(changes):
    with pytest.raises(ValidationError):
        SocialContent(platform="HN", **{"native_id": "1", **changes})


@pytest.mark.parametrize("platform", ENDPOINTS)
@pytest.mark.pit
def test_native_duplicate_update_aba_pit_and_no_fact(setup_ledger, platform):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base, platform)
    first = run(ledger, clock, source, review, seed, body(platform))
    item = first["observations"][0]
    cutoff = clock()
    old = ledger.replay(cutoff)
    assert first["lifecycle"] == ("NEW",)
    duplicate = run(ledger, clock, source, review, seed, body(platform), "duplicate")
    assert duplicate["lifecycle"] == ("DUPLICATE",)
    assert duplicate["observations"][0] == item
    second = run(ledger, clock, source, review, seed, body(platform, "B"), "second")
    third = run(ledger, clock, source, review, seed, body(platform), "third")
    assert second["lifecycle"] == third["lifecycle"] == ("UPDATED",)
    assert third["observations"][0].version == 3
    assert third["observations"][0].first_seen_at == item.first_seen_at
    assert ledger.replay(cutoff) == old
    assert all(e.fact_state == "UNVERIFIED" for e in ledger.history(as_of=clock(), kind="EventVersion"))
    assert all(e.claim_kind == "NARRATIVE" for e in ledger.history(as_of=clock(), kind="EvidenceVersion"))
    assert {n.classification for n in ledger.history(as_of=clock(), kind="NoveltyDecision")} <= {"R0", "R1", "UNDETERMINED"}
    assert ledger.raw(item.raw_ref) == json.dumps(body(platform), separators=(",", ":"), ensure_ascii=False).encode()
    with pytest.raises(ValidationError):
        SocialObservation.model_validate({**item.model_dump(), "received_at": "2099-01-01T00:00:00Z"})


@pytest.mark.parametrize("platform", ENDPOINTS)
def test_restart_restores_cursor_and_dedupe(setup_ledger, platform):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base, platform)
    first = run(ledger, clock, source, review, seed, body(platform))
    prior = cursor_for(ledger, source)
    ledger.close()
    reopened = Ledger(ledger.path, clock=clock)
    try:
        assert cursor_for(reopened, source) == prior
        result = run(reopened, clock, source, review, seed, body(platform), "restart")
        assert result["observations"] == first["observations"]
        assert result["lifecycle"] == ("DUPLICATE",)
    finally:
        reopened.close()


@pytest.mark.parametrize("failure", ["timeout", "429", "500", "404", "redirect", "json"])
def test_failure_cursor_and_source_health_isolation(setup_ledger, failure):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base)
    other, other_review = configure(ledger, clock, base, "BLUESKY")
    run(ledger, clock, other, other_review, seed, body("BLUESKY"), "other")
    run(ledger, clock, source, review, seed, body("HN"))
    prior = cursor_for(ledger, source)
    other_prior = cursor_for(ledger, other)
    calls = []
    def response(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("offline", request=request)
        if failure == "json":
            return httpx.Response(200, content=b"{broken")
        return httpx.Response(302 if failure == "redirect" else int(failure), headers={"Retry-After": "600"})
    adapter = HTTPAdapter(transport=httpx.MockTransport(response), clock=clock, attempts=1)
    try:
        result = collect_social(ledger, adapter, source, review, seed, attempt_key="failed")
    finally:
        adapter.close()
    assert result["status"] == "SOURCE_UNAVAILABLE" and len(calls) == 1
    after = cursor_for(ledger, source)
    assert after.cursor == prior.cursor and after.last_success_at == prior.last_success_at
    assert cursor_for(ledger, other) == other_prior
    health = ledger.history(as_of=clock(), kind="SourceHealth")[-1]
    assert health.source_id == source.source_id and health.health == "SOURCE_UNAVAILABLE"


def test_authorization_hold_before_network(setup_ledger):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base, qualification_status="HOLD_SOURCE_AUTHORIZATION",
                             raw_retention_status="UNKNOWN")
    calls = []
    adapter = HTTPAdapter(transport=httpx.MockTransport(lambda r: calls.append(r)), clock=clock)
    try:
        result = collect_social(ledger, adapter, source, review, seed, attempt_key="hold")
    finally:
        adapter.close()
    assert result["status"] == "HOLD_SOURCE_AUTHORIZATION" and calls == []


def test_missing_is_not_deletion_and_explicit_delete_is_append(setup_ledger):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base)
    original = run(ledger, clock, source, review, seed, body("HN"))["observations"][0]
    missing = run(ledger, clock, source, review, seed, None, "missing")["observations"][0]
    assert missing.deletion_state == "DELETED_OR_MISSING_UNKNOWN"
    deleted = run(ledger, clock, source, review, seed, {"id": 123, "deleted": True}, "deleted")["observations"][0]
    assert deleted.deletion_state == "EXPLICIT_DELETED" and deleted.version == 3
    assert any(c.change_type == "DELETE" for c in ledger.history(as_of=clock(), kind="EvidenceChange"))
    assert ledger.raw(original.raw_ref)


@pytest.mark.parametrize("same_url", [True, False])
def test_origin_exact_url_only(setup_ledger, same_url):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base)
    hn = body("HN")
    hn["url"] = "https://original.example/report"
    first = run(ledger, clock, source, review, seed, hn)["observations"][0]
    bs, br = configure(ledger, clock, base, "BLUESKY")
    data = body("BLUESKY")
    data["posts"][0]["embed"] = {"external": {"uri": hn["url"] if same_url else hn["url"] + "?other"}}
    second = run(ledger, clock, bs, br, seed, data, "bsky")["observations"][0]
    e1 = ledger.get(**ref(first.evidence_refs[0]))
    e2 = ledger.get(**ref(second.evidence_refs[0]))
    assert (e1.origin_cluster_id == e2.origin_cluster_id) is same_url
    assert e2.independence_status == "UNKNOWN"


@pytest.mark.parametrize("platform,raw", [("HN", '{"id":123}'), ("HN", '[true]'),
    ("HN", '{"id":123,"type":"comment"}'), ("BLUESKY", '{}'), ("MASTODON", '{}')])
def test_malformed_provider_shapes(platform, raw):
    with pytest.raises(SourceUnavailable):
        normalize(platform, raw, instance="social.example")


def test_hn_discovery_lists():
    assert normalize("HN", '[1,3,2]') == ((), "3")
    assert normalize("HN", '{"items":[1,4],"profiles":[]}') == ((), "4")


@pytest.mark.parametrize("stage", ["before_commit", "after_commit", "before_receipt_commit"])
@pytest.mark.pit
def test_crash_retry_and_cursor_suffix_recovery(setup_ledger, stage):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base)
    def crash(point):
        if point == stage:
            raise RuntimeError("OFFLINE_CRASH")
    ledger.fault = crash
    with pytest.raises(RuntimeError, match="OFFLINE_CRASH"):
        run(ledger, clock, source, review, seed, body("HN"))
    assert cursor_for(ledger, source) is None
    ledger.fault = lambda _: None
    ledger.recover()
    result = run(ledger, clock, source, review, seed, body("HN"), "recovery")
    assert len(result["observations"]) == 1 and cursor_for(ledger, source).cursor == "123"


def test_cursor_commit_failure_retries_without_new_social(setup_ledger, monkeypatch):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base)
    original = ledger.collector_result
    def fail(*args, **kwargs):
        raise RuntimeError("CURSOR_WRITE")
    monkeypatch.setattr(ledger, "collector_result", fail)
    with pytest.raises(RuntimeError, match="CURSOR_WRITE"):
        run(ledger, clock, source, review, seed, body("HN"))
    assert cursor_for(ledger, source) is None
    monkeypatch.setattr(ledger, "collector_result", original)
    result = run(ledger, clock, source, review, seed, body("HN"), "retry")
    assert result["lifecycle"] == ("DUPLICATE",)
    assert len(ledger.history(as_of=clock(), kind="SocialObservation")) == 1


def test_endpoint_scope():
    for endpoint in ["http://hacker-news.firebaseio.com/v0/newstories.json",
                     "https://user:pass@hacker-news.firebaseio.com/v0/newstories.json",
                     "https://other.example/v0/newstories.json"]:
        with pytest.raises(ValueError):
            endpoint_gate("HN", endpoint)


@pytest.mark.parametrize("platform,param", [("BLUESKY", "cursor"), ("MASTODON", "since_id")])
def test_resume_uses_durable_provider_parameter(setup_ledger, platform, param):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base, platform)
    run(ledger, clock, source, review, seed, body(platform))
    previous = cursor_for(ledger, source)
    calls = []
    def response(request):
        calls.append(request)
        assert request.url.params[param] == previous.cursor
        return httpx.Response(200, json=body(platform))
    with_adapter = HTTPAdapter(transport=httpx.MockTransport(response), clock=clock, attempts=1)
    try:
        collect_social(ledger, with_adapter, source, review, seed, attempt_key="resume")
    finally:
        with_adapter.close()
    assert len(calls) == 1


@pytest.mark.parametrize("changes", [
    {"raw_retention_status": "UNKNOWN"}, {"authentication_required": True},
    {"authentication_required": None}])
def test_qualification_cannot_assume_authorization(setup_ledger, changes):
    ledger, clock, base, _ = setup_ledger
    with pytest.raises(ValidationError, match="HOLD_SOURCE_AUTHORIZATION"):
        configure(ledger, clock, base, **changes)


def test_review_binding_cannot_be_swapped(setup_ledger):
    ledger, clock, base, seed = setup_ledger
    source, review = configure(ledger, clock, base)
    altered = SourceQualification.model_validate({**review.model_dump(), "authorization_proof": "different proof"})
    assert run(ledger, clock, source, altered, seed, body("HN"))["status"] == "HOLD_SOURCE_AUTHORIZATION"
