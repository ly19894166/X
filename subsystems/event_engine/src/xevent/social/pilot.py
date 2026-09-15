"""Minimal D wrapper over the original Phase 2 ledger and HTTP adapter.

Publication is response -> social -> cursor. An interrupted suffix is repaired by
retrying the unchanged response; no cursor acknowledges unpublished social rows.
"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..adapters.http import AuthorizationHold, SourceUnavailable, authorization_gate
from ..contracts.common import VersionRef
from ..contracts.models import Source
from ..ledger.contracts import EventSeed, RawObservation
from ..ledger.store import MODELS, digest, ref
from .contracts import SocialObservation
from .providers import endpoint_gate, normalize

MODELS["SocialObservation"] = SocialObservation


def review_binding(review):
    return "D_SOCIAL_REVIEW:" + digest(review.model_dump(mode="json"))


def cursor_for(ledger, source):
    return max((x for x in ledger.history(as_of=ledger.now(), kind="CollectorCursor")
                if x.source_id == source.source_id), key=lambda x: x.version, default=None)


def request_source(source, platform, previous, resume):
    u = urlsplit(source.canonical_locator)
    query = dict(parse_qsl(u.query))
    allowed = {"BLUESKY": {"q", "actor", "limit", "sort", "cursor"},
               "HN": set(), "MASTODON": {"local", "limit", "since_id", "min_id"}}[platform]
    if set(query) - allowed:
        raise AuthorizationHold("SOCIAL_QUERY_NOT_QUALIFIED")
    if resume and previous and previous.cursor:
        if platform == "BLUESKY":
            query["cursor"] = previous.cursor
        elif platform == "MASTODON":
            query["since_id"] = previous.cursor
    locator = urlunsplit((u.scheme, u.netloc, u.path, urlencode(query), ""))
    # Only documented pagination is added to the exact registered endpoint.
    # The raw locator keeps the actual request; source_ref keeps the fixed review.
    return Source.model_validate({**source.model_dump(), "canonical_locator": locator})


def _seed(seed, identity):
    return EventSeed(event_id="SOCIAL_EVENT:" + digest(identity),
                     title_zh="社交线索：需要正式来源调查", dna=seed.dna)


def _publish(ledger, source, content, response, seed):
    identity = "SOCIAL:" + digest([content.platform, content.native_id])
    prior = max((r for r in ledger.history(as_of=ledger.now(), kind="SocialObservation")
                 if r.object_id == identity), key=lambda r: r.version, default=None)
    fingerprint = digest(content.model_dump(mode="json"))
    if prior and prior.normalized_hash == fingerprint:
        return prior, "DUPLICATE"
    # Exact URL is only an explicit citation association, never independent truth.
    links = {v for v in (content.canonical_url, content.original_url) if v}
    matched = next((s for s in ledger.history(as_of=ledger.now(), kind="SocialObservation")
                    if s.platform != content.platform and links.intersection(
                        v for v in (s.canonical_url, s.original_url) if v)), None)
    raw = RawObservation(source_ref=ref(source), locator=identity, raw=response.raw,
        first_seen_at=prior.first_seen_at if prior else response.first_seen_at,
        collected_at=response.collected_at, published_at=content.created_at,
        content_version=fingerprint, claim_kind="NARRATIVE",
        origin_ref=matched.evidence_refs[0] if matched else None)
    raw = ledger.reception_version(raw)
    if content.deletion_state == "EXPLICIT_DELETED" and raw.change_type == "EDIT":
        raw = RawObservation.model_validate({**raw.model_dump(), "change_type": "DELETE"})
    evidence = ledger.ingest(raw, _seed(seed, identity))
    version = prior.version + 1 if prior else 1
    lifecycle = "DELETED_OR_MISSING_UNKNOWN" if content.deletion_state != "NOT_REPORTED" else (
        "UPDATED" if prior else "NEW")
    payload = {**content.model_dump(mode="json"), "source_ref": ref(source),
        "first_seen_at": (prior.first_seen_at if prior else response.first_seen_at).isoformat(),
        "received_at": response.collected_at.isoformat(), "raw_ref": evidence.raw_object_ref,
        "response_locator": response.locator, "normalized_hash": fingerprint,
        "lifecycle": lifecycle, "evidence_refs": [ref(evidence)],
        "supersedes_version": prior.version if prior else None,
        "policy_version": "D_SOCIAL_SIGNAL_V0.1"}
    inputs = [ref(source), ref(evidence)] + ([ref(prior)] if prior else [])
    ledger._write(f"{identity}:{version}", digest(payload),
        lambda conn, view, batch: ledger._put(conn, batch, "SocialObservation", identity, version, payload, inputs))
    return ledger.get(identity, version), lifecycle


def collect_social(ledger, adapter, source, review, seed, *, attempt_key, resume=True):
    if ledger.get(source.object_id, source.version) != source:
        raise ValueError("SOURCE_VERSION_CONFLICT")
    attempted = ledger.now()
    previous = cursor_for(ledger, source)
    try:
        if (review.qualification_status != "QUALIFIED" or review.reviewed_at > attempted
                or source.retention_policy != review_binding(review)
                or source.canonical_locator != review.endpoint or source.platform != review.platform):
            raise AuthorizationHold("HOLD_SOURCE_AUTHORIZATION")
        authorization_gate(source, attempted)
        endpoint_gate(review.platform, review.endpoint)
        target = request_source(source, review.platform, previous, resume)
        result = adapter.fetch(target)
        if result.observation is None:
            raise SourceUnavailable("SOCIAL_EMPTY_HTTP_RESPONSE")
        raw = result.observation
        u = urlsplit(target.canonical_locator)
        expected = u.path.rsplit("/", 1)[-1].removesuffix(".json") if "/item/" in u.path else None
        rows, cursor = normalize(review.platform, raw.raw, expected_id=expected, instance=u.netloc)
        # Archive the exact successful JSON response, including empty discovery lists.
        # Feed response events are unverified transport envelopes, not independent facts.
        response_evidence = ledger.ingest(ledger.reception_version(raw),
                            _seed(seed, [source.source_id, "RESPONSE", raw.locator]))
        outputs = [_publish(ledger, source, row, raw, seed) for row in rows]
        if review.platform in ("HN", "MASTODON") and previous and previous.cursor:
            cursor = str(max(int(cursor or previous.cursor), int(previous.cursor)))
        ledger.collector_result(VersionRef(**ref(source)), attempt_key=attempt_key,
            attempted_at=attempted, received_at=result.received_at, success=True,
            cursor=cursor if cursor is not None else (previous.cursor if previous else None),
            since_id=cursor if review.platform == "MASTODON" else None,
            received_evidence_refs=[VersionRef(**ref(response_evidence))],
            detail_zh="SOCIAL_LEAD / EVENT_INVESTIGATION_REQUIRED；不构成事实确认")
        return {"status": "SOCIAL_LEAD", "observations": tuple(x for x, _ in outputs),
                "lifecycle": tuple(state for _, state in outputs)}
    except (AuthorizationHold, SourceUnavailable) as exc:
        ledger.collector_result(VersionRef(**ref(source)), attempt_key=attempt_key,
            attempted_at=attempted, success=False, detail_zh=str(exc),
            authorization_hold=isinstance(exc, AuthorizationHold))
        return {"status": "HOLD_SOURCE_AUTHORIZATION" if isinstance(exc, AuthorizationHold)
                else "SOURCE_UNAVAILABLE", "observations": (), "lifecycle": ()}
