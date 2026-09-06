import json

import httpx
import pytest
from pydantic import ValidationError

from test_phase2_ledger import setup_ledger, obs
from xevent.adapters.http import AuthorizationHold, HTTPAdapter, SourceUnavailable
from xevent.contracts import Source
from xevent.discovery.novelty import classify
from xevent.ledger.store import ref
from xevent.runtime.collector import collect_once


def authorized(source):
    return Source.model_validate({**source.model_dump(), "enabled": True, "terms_status": "REVIEWED",
                                 "authorization_status": "AUTHORIZED", "allowed_uses": ["EVENT_RESEARCH"],
                                 "raw_retention_allowed": True, "canonical_locator": "https://official.example/feed"})


def register_authorized(ledger, source):
    return ledger.register_source(Source.model_validate({**authorized(source).model_dump(), "version": 2, "supersedes_version": 1}))


@pytest.mark.parametrize("changes", [
    {"authorization_status": "DENIED"}, {"authorization_status": "UNKNOWN"}, {"enabled": False},
    {"terms_status": "UNKNOWN"}, {"allowed_uses": []}, {"raw_retention_allowed": None},
    {"access_restrictions": ["每次必须人工批准"]}])
def test_authorization_before_any_network_request(setup_ledger, changes):
    ledger, clock, source, seed = setup_ledger
    source = Source.model_validate({**authorized(source).model_dump(), **changes})
    calls = []
    adapter = HTTPAdapter(transport=httpx.MockTransport(lambda r: calls.append(r)), clock=clock)
    with pytest.raises(AuthorizationHold):
        adapter.fetch(source)
    assert calls == []
    adapter.close()


@pytest.mark.parametrize("authorization", ["AUTHORIZED", "NOT_REQUIRED"])
def test_official_raw_observation_and_explicit_http_settings(setup_ledger, authorization):
    ledger, clock, source, seed = setup_ledger
    source = Source.model_validate({**authorized(source).model_dump(), "authorization_status": authorization})
    def respond(request):
        assert request.headers["User-Agent"].startswith("X-Event-Engine/")
        assert request.extensions["timeout"]["connect"] == 5
        return httpx.Response(200, content=b"official statement")
    adapter = HTTPAdapter(transport=httpx.MockTransport(respond), clock=clock)
    result = adapter.fetch(source)
    assert result.observation.raw == b"official statement"
    assert result.observation.published_at is None
    assert result.observation.first_seen_at <= result.observation.collected_at
    adapter.close()


def test_timeout_bounded_and_source_failure_isolation(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    source = register_authorized(ledger, source)
    calls, sleeps = [], []
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("offline timeout", request=request)
    adapter = HTTPAdapter(transport=httpx.MockTransport(timeout), clock=clock, sleep=sleeps.append)
    result = collect_once(ledger, adapter, source, seed, attempt_key="timeout1")
    assert result["status"] == "SOURCE_UNAVAILABLE" and len(calls) == 3 and len(sleeps) == 2
    assert ledger.history(as_of=clock(), kind="SourceHealth")[-1].health == "SOURCE_UNAVAILABLE"
    adapter.close()
    good = HTTPAdapter(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ok")), clock=clock)
    assert collect_once(ledger, good, source, seed, attempt_key="success2")["status"] == "CURRENT_OBSERVATION_ONLY"
    good.close()


def test_429_retry_after_respected_and_bounded(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    sleeps, calls = [], []
    def response(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "2"})
    adapter = HTTPAdapter(transport=httpx.MockTransport(response), clock=clock, sleep=sleeps.append)
    with pytest.raises(SourceUnavailable):
        adapter.fetch(authorized(source))
    assert len(calls) == 3 and sleeps == [2.0, 2.0]
    adapter.close()


@pytest.mark.parametrize("retry_after", ["600", "NaN", "invalid"])
def test_retry_after_long_or_invalid_is_hold_without_early_retry(setup_ledger, retry_after):
    ledger, clock, source, seed = setup_ledger
    calls = []
    def response(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": retry_after})
    adapter = HTTPAdapter(transport=httpx.MockTransport(response), clock=clock, sleep=lambda _: pytest.fail("不应等待后提前重试"))
    with pytest.raises(SourceUnavailable):
        adapter.fetch(authorized(source))
    assert len(calls) == 1
    adapter.close()


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404])
def test_permanent_http_errors_and_redirect_not_retried(setup_ledger, status):
    ledger, clock, source, seed = setup_ledger
    calls = []
    def response(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://other.example/"})
    adapter = HTTPAdapter(transport=httpx.MockTransport(response), clock=clock)
    with pytest.raises(SourceUnavailable):
        adapter.fetch(authorized(source))
    assert len(calls) == 1
    adapter.close()


def test_rss_parser_uses_exact_response_bytes_and_does_not_fetch_links(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    raw = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Offline</title><link>https://official.example/</link><description>fixture</description><item><guid>001</guid><title>Policy</title><link>https://never-request.example/1</link></item></channel></rss>'
    calls = []
    def response(request):
        calls.append(request)
        return httpx.Response(200, content=raw, headers={"ETag": "etag1"})
    adapter = HTTPAdapter(transport=httpx.MockTransport(response), clock=clock)
    result = adapter.fetch(authorized(source), rss=True)
    assert result.observation.raw == raw and result.entries[0]["id"] == "001"
    assert len(calls) == 1 and result.etag == "etag1"
    adapter.close()


@pytest.mark.pit
def test_collector_retry_reversion_and_304_cursor(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    source = register_authorized(ledger, source)
    responses = [b"A", b"A", b"B", b"A", None]
    def response(request):
        raw = responses.pop(0)
        if raw is None:
            assert request.headers["If-None-Match"] == "A"
            return httpx.Response(304)
        return httpx.Response(200, content=raw, headers={"ETag": raw.decode()})
    adapter = HTTPAdapter(transport=httpx.MockTransport(response), clock=clock)
    for n in range(5):
        assert collect_once(ledger, adapter, source, seed, attempt_key=str(n))["status"] == "CURRENT_OBSERVATION_ONLY"
    evidence = ledger.history(as_of=clock(), kind="EvidenceVersion")
    assert [ledger.raw(e.raw_object_ref) for e in evidence] == [b"A", b"B", b"A"]
    assert len(ledger.history(as_of=clock(), kind="CollectorCursor")) == 5
    adapter.close()


def test_r2_requires_complete_source_structured_fields(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    first = obs(clock, source, json.dumps({"detail": "a"}), structured_fields={"detail": "a"}, structured_basis="SOURCE_STRUCTURED")
    second = obs(clock, source, json.dumps({"detail": "b"}), "2", structured_fields={"detail": "b"}, structured_basis="SOURCE_STRUCTURED", change_type="EDIT")
    assert classify(second, first)[0] == "R2"
    with pytest.raises(ValidationError, match="FIELD_PROOF"):
        obs(clock, source, '正文同时新增重大内容 {"detail":"b"}', structured_fields={"detail": "b"}, structured_basis="SOURCE_STRUCTURED")


@pytest.mark.parametrize("body", [b"not RSS", b"x" * 100])
def test_invalid_rss_or_size_failure_isolated(setup_ledger, body):
    ledger, clock, source, seed = setup_ledger
    adapter = HTTPAdapter(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)), clock=clock, max_bytes=50)
    with pytest.raises(SourceUnavailable):
        adapter.fetch(authorized(source), rss=True)
    adapter.close()


def test_registry_authorization_cannot_be_overridden_in_memory(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    adapter = HTTPAdapter(transport=httpx.MockTransport(lambda r: pytest.fail("不得请求")), clock=clock)
    with pytest.raises(ValueError, match="SOURCE_VERSION_CONFLICT"):
        collect_once(ledger, adapter, authorized(source), seed, attempt_key="override")
    result = collect_once(ledger, adapter, source, seed, attempt_key="denied")
    assert result["status"] == "AUTHORIZATION_HOLD"
    assert ledger.history(as_of=clock(), kind="SourceHealth")[-1].health == "AUTHORIZATION_HOLD"
    adapter.close()
