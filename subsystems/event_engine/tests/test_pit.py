from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from factories import seal, ts
from xevent.contracts import Actor, ActorTopicProfile, EvidenceVersion, EventVersion, NarrativeSourceProfile, Source
from xevent.contracts.bundle import OfflineFixture
from xevent.contracts.common import DerivedEnvelope, PITError, PITQuery, UTCDateTime, VersionEnvelope

pytestmark = pytest.mark.pit


@pytest.mark.parametrize("value", ["2026-09-06T10:00:00", datetime(2026, 9, 6), 1788679200, "2026-09-06"])
def test_naive_or_numeric_time_refused(value):
    with pytest.raises(ValidationError):
        TypeAdapter(UTCDateTime).validate_python(value)


@pytest.mark.parametrize("value", ["2026-09-06T10:00:05+08:00", "2026-09-06T02:00:05Z", datetime(2026, 9, 6, 2, 0, 5, tzinfo=timezone.utc)])
def test_timezone_normalized(value):
    actual = TypeAdapter(UTCDateTime).validate_python(value)
    assert actual == datetime(2026, 9, 6, 2, 0, 5, tzinfo=timezone.utc)
    assert actual.tzinfo == timezone.utc


@pytest.mark.parametrize("recorded,as_of,visible", [(5, 3, False), (5, 5, True), (7, 6, False), (7, 7, True)])
def test_second_level_ready_and_durable_gate(payload, recorded, as_of, visible):
    evidence = EvidenceVersion.model_validate({**payload["evidence_versions"][0], "recorded_at": ts(recorded), "available_at": ts(recorded)})
    assert evidence.collected_at.second == 2 and evidence.ready_at.second == 5
    assert evidence.is_visible(PITQuery(as_of=ts(as_of), mode="LIVE_FORWARD")) is visible


@pytest.mark.parametrize("field", ["ready_at", "recorded_at", "collected_at", "first_seen_at"])
@pytest.mark.parametrize("missing", [True, False])
def test_required_raw_times(payload, field, missing):
    data = payload["evidence_versions"][0]
    if missing:
        del data[field]
    else:
        data[field] = None
    with pytest.raises(ValidationError):
        EvidenceVersion.model_validate(data)


def test_cannot_backdate_availability(payload):
    data = payload["evidence_versions"][0]
    with pytest.raises(ValidationError, match="PIT_RECORDED"):
        EvidenceVersion.model_validate({**data, "available_at": ts(3)})
    with pytest.raises(ValidationError, match="PIT_EVIDENCE"):
        EvidenceVersion.model_validate({**data, "ready_at": ts(7)})


def test_effective_date_never_implies_knowledge(payload):
    data = {**payload["evidence_versions"][0], "effective_from": "2026-09-01T00:00:00+08:00"}
    record = EvidenceVersion.model_validate(data)
    assert not record.is_visible(PITQuery(as_of=ts(3), mode="LIVE_FORWARD"))
    assert record.is_visible(PITQuery(as_of=ts(5), mode="LIVE_FORWARD"))


def test_future_actor_role_not_backfilled(payload):
    data = payload["actors"][0]
    old = Actor.model_validate(data)
    future = Actor.model_validate({**data, "version": 2, "supersedes_version": 1, "role_title_zh": "未来新职位",
                    "term_effective_from": ts(), "effective_from": ts(), "recorded_at": ts(20), "available_at": ts(20)})
    query = PITQuery(as_of=ts(10), mode="LIVE_FORWARD")
    assert old.is_visible(query) and old.role_title_zh is None
    assert not future.is_visible(query)


def test_half_open_effective_interval(payload):
    record = EvidenceVersion.model_validate({**payload["evidence_versions"][0], "effective_from": ts(), "effective_to": ts(10)})
    assert record.is_visible(PITQuery(as_of=ts(9), mode="LIVE_FORWARD"))
    assert not record.is_visible(PITQuery(as_of=ts(10), mode="LIVE_FORWARD"))


def test_derived_inputs_compute_and_recorded_gates(payload):
    data = payload["event_versions"][0]
    for changes in ({"computed_at": ts(4)}, {"computed_at": ts(10)}, {"recorded_at": ts(10)}):
        with pytest.raises(ValidationError, match="PIT_"):
            EventVersion.model_validate({**data, **changes})
    record = EventVersion.model_validate(data)
    assert not record.is_visible(PITQuery(as_of=ts(7), mode="LIVE_FORWARD"))


def test_fake_input_timestamp_refused_by_bundle(payload):
    data = payload["event_versions"][0]
    for input_ref in data["input_version_refs"]:
        if input_ref["object_id"] == "EVD_001":
            input_ref["available_at"] = ts(1)
    payload["event_versions"][0] = seal(EventVersion.model_validate(data)).model_dump(mode="json")
    with pytest.raises(ValidationError, match="PIT_REFERENCE_TIME"):
        OfflineFixture.model_validate(payload)


def test_bundle_hold_input_never_becomes_ready_event(payload):
    data = payload["sources"][0]
    data.update(status="HOLD", reason_codes=["等待身份核验"])
    payload["sources"][0] = seal(Source.model_validate(data)).model_dump(mode="json")
    with pytest.raises(ValidationError, match="PIT_NOT_VISIBLE"):
        OfflineFixture.model_validate(payload)


def test_bundle_replay_input_not_mixed_into_live(payload):
    data = payload["sources"][0]
    data["mode"] = "OBSERVED_REPLAY"
    payload["sources"][0] = seal(Source.model_validate(data)).model_dump(mode="json")
    with pytest.raises(ValidationError, match="PIT_MODE"):
        OfflineFixture.model_validate(payload)


@pytest.mark.parametrize("quality", ["UNVERIFIED", "REJECTED"])
def test_failed_validation_never_formal_evidence(payload, quality):
    data = payload["evidence_versions"][0]
    with pytest.raises(ValidationError, match="EVIDENCE_NOT_READY"):
        EvidenceVersion.model_validate({**data, "quality_status": quality})
    record = EvidenceVersion.model_validate({**data, "quality_status": quality, "status": "QUARANTINED", "reason_codes": ["等待人工校验"]})
    assert not record.is_visible(PITQuery(as_of=ts(30), mode="LIVE_FORWARD"))


def public_envelope():
    return dict(object_id="PUBLIC_001", version=1, recorded_at=ts(30), available_at=ts(30), run_id="PUBLIC_ONLY",
                policy_version="P1", content_hash="0" * 64, mode="PUBLIC_PIT_RESEARCH", public_pit=dict(
                    public_available_at=ts(), research_available_at=ts(2), simulated_latency_seconds=2.0,
                    availability_proof="fixture:不可变历史版本与公开时间证明"))


def test_public_research_separate_from_actual_time():
    record = VersionEnvelope.model_validate(public_envelope())
    assert record.available_at.second == 30
    assert record.is_visible(PITQuery(as_of=ts(2), mode="PUBLIC_PIT_RESEARCH"))
    assert not record.is_visible(PITQuery(as_of=ts(1), mode="PUBLIC_PIT_RESEARCH"))
    for mode in ("LIVE_FORWARD", "OBSERVED_REPLAY"):
        with pytest.raises(PITError, match="PIT_MODE"):
            record.is_visible(PITQuery(as_of=ts(40), mode=mode))


def test_live_replay_mode_boundary(payload):
    data = payload["evidence_versions"][0]
    live = EvidenceVersion.model_validate(data)
    assert live.is_visible(PITQuery(as_of=ts(5), mode="OBSERVED_REPLAY"))
    with pytest.raises(PITError):
        live.is_visible(PITQuery(as_of=ts(5), mode="PUBLIC_PIT_RESEARCH"))
    replay = EvidenceVersion.model_validate({**data, "mode": "OBSERVED_REPLAY"})
    with pytest.raises(PITError):
        replay.is_visible(PITQuery(as_of=ts(5), mode="LIVE_FORWARD"))


def test_public_proof_latency_and_computation():
    data = public_envelope()
    with pytest.raises(ValidationError):
        VersionEnvelope.model_validate({**data, "public_pit": None})
    with pytest.raises(ValidationError):
        VersionEnvelope.model_validate({**data, "public_pit": {**data["public_pit"], "simulated_latency_seconds": 3.0}})
    with pytest.raises(ValidationError, match="PIT_PUBLIC_COMPUTE"):
        DerivedEnvelope.model_validate({**data, "computed_at": ts(20)})
    valid = DerivedEnvelope.model_validate({**data, "computed_at": ts(20), "research_computed_at": ts(1)})
    assert valid.is_visible(PITQuery(as_of=ts(2), mode="PUBLIC_PIT_RESEARCH"))


@pytest.mark.parametrize("metric", ["leading_stats", "following_stats", "posthoc_stats", "edit_stats", "delete_stats"])
def test_future_narrative_outcomes_cannot_backfill(payload, metric):
    data = payload["narrative_source_profiles"][0]
    data[metric] = dict(numerator=1, denominator=1, rate=1.0, outcome_available_at=ts(20))
    with pytest.raises(ValidationError, match="PIT_STATS"):
        NarrativeSourceProfile.model_validate(data)


def test_narrative_window_and_availability(payload):
    data = payload["narrative_source_profiles"][0]
    record = NarrativeSourceProfile.model_validate(data)
    assert not record.is_visible(PITQuery(as_of=ts(8), mode="LIVE_FORWARD"))
    data["observation_window"]["end"] = ts(10)
    with pytest.raises(ValidationError, match="PIT_WINDOW"):
        NarrativeSourceProfile.model_validate(data)


def test_actor_realization_no_future_backfill(payload):
    data = payload["actor_topic_profiles"][0]
    data.update(realized_count=1, unresolved_count=0, outcome_available_at=ts(20))
    with pytest.raises(ValidationError, match="PIT_STATS"):
        ActorTopicProfile.model_validate(data)


def test_public_statistics_use_simulated_cutoff(payload):
    data = payload["narrative_source_profiles"][0]
    data.update(mode="PUBLIC_PIT_RESEARCH", computed_at=ts(20), recorded_at=ts(30), available_at=ts(30),
                public_pit=public_envelope()["public_pit"], research_computed_at=ts(2))
    for ref in data["input_version_refs"]:
        ref["research_available_at"] = ts(1)
    # 实际计算较晚也不能把未来观察窗放入过去模拟。
    with pytest.raises(ValidationError, match="PIT_WINDOW"):
        NarrativeSourceProfile.model_validate(data)
