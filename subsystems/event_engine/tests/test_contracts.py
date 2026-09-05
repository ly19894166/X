import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from factories import build_fixture, seal, ts
from xevent.contracts import SCHEMAS, ActorTopicProfile, EventDNA, EventVersion, NarrativeSourceProfile, Source, Statement
from xevent.contracts.bundle import OfflineFixture
from xevent.contracts.common import Code6, SampleStatistic, VersionRef
from xevent.contracts.external import normalize_external
from xevent.contracts.models import FactState, NarrativeState, PricingState, MappingState, Grade, ImpactDirection


def test_offline_fixture_and_reproducible_generation(payload):
    assert build_fixture() == payload
    fixture = OfflineFixture.model_validate(payload)
    assert len(list(fixture.records())) == 9
    assert fixture.event_versions[0].fact_state == "UNVERIFIED"
    assert fixture.evidence_versions[0].claim_kind == "INTENT"


@pytest.mark.parametrize("model", list(SCHEMAS.values()))
def test_json_schema_generation(model):
    schema = model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert json.loads(json.dumps(schema)) == schema


def test_json_roundtrip(payload):
    fixture = OfflineFixture.model_validate(payload)
    assert OfflineFixture.model_validate_json(fixture.model_dump_json()) == fixture
    for record in fixture.records():
        assert type(record).model_validate_json(record.model_dump_json()) == record


def test_exported_schema_is_frozen():
    path = Path(__file__).parents[1] / "configs" / "schemas_v0.1.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {name: model.model_json_schema() for name, model in SCHEMAS.items()}


def test_code6_preserves_leading_zero():
    adapter = TypeAdapter(Code6, config={"strict": True})
    assert adapter.validate_python("000001") == "000001"
    for bad in (1, 123456, "1", "000001.SZ", True):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


@pytest.mark.parametrize("enum", [FactState, NarrativeState, PricingState, MappingState, Grade, ImpactDirection])
def test_internal_enums_fail_closed(enum):
    with pytest.raises(ValidationError):
        TypeAdapter(enum).validate_python("NEW_UNLISTED_STATE")


@pytest.mark.parametrize("field", ["fact_state", "narrative_state", "pricing_state"])
def test_event_internal_states_not_normalized(payload, field):
    data = payload["event_versions"][0]
    data[field] = "NEW_UNLISTED_STATE"
    with pytest.raises(ValidationError):
        EventVersion.model_validate(data)


def test_external_statement_unknown_keeps_evidence(payload):
    data = payload["statements"][0]
    data["statement_type"] = "新出现的线下语音场景"
    normalized = normalize_external(data, "statement_type")
    record = Statement.model_validate(normalized)
    assert record.statement_type == "OTHER" and record.raw_type == data["statement_type"]
    assert record.claim_kind == "INTENT" and record.policy_certainty == "UNKNOWN"
    payload["statements"][0] = seal(record).model_dump(mode="json")
    bundle = OfflineFixture.model_validate(payload)
    assert len(bundle.evidence_versions) == 1
    assert bundle.event_versions[0].fact_state == "UNVERIFIED"


@pytest.mark.parametrize("group,field", [("evidence_versions", "evidence_type"), ("event_versions", "event_type")])
def test_external_other_categories(payload, group, field):
    record_type = type(getattr(OfflineFixture.model_validate(payload), group)[0])
    normalized = normalize_external({**payload[group][0], field: "新外部类别"}, field)
    record = record_type.model_validate(normalized)
    assert record.raw_type == "新外部类别"
    assert getattr(record, field) == "OTHER"


def test_external_missing_and_raw_conflict(payload):
    data = {**payload["statements"][0], "statement_type": None}
    result = Statement.model_validate(normalize_external(data, "statement_type"))
    assert result.statement_type == "UNKNOWN" and result.raw_type is None
    assert result.classification_missing_reason
    with pytest.raises(ValueError, match="EXTERNAL_RAW_CONFLICT"):
        normalize_external({"statement_type": "新类别", "raw_type": "不同原值"}, "statement_type")


def test_external_known_original_and_normalized_other_are_preserved():
    assert normalize_external({"statement_type": "SPEECH"}, "statement_type")["raw_type"] == "SPEECH"
    data = {"statement_type": "OTHER", "raw_type": "新场景"}
    assert normalize_external(data, "statement_type") == data
    assert normalize_external({"statement_type": None, "raw_type": "分类尚待确认"}, "statement_type")["raw_type"] == "分类尚待确认"


def test_evidence_relation_all_directions(payload):
    fixture = OfflineFixture.model_validate(payload)
    original = fixture.evidence_relations[0]
    for relation in ("SUPPORTS", "CONTRADICTS", "CONTEXT"):
        record = type(original).model_validate({**original.model_dump(), "relation": relation})
        assert record.relation == relation


def test_narrative_metric_count_cannot_exceed_sample(payload):
    data = payload["narrative_source_profiles"][0]
    data["leading_stats"] = dict(numerator=1, denominator=2, rate=0.5, outcome_available_at=ts(5))
    with pytest.raises(ValidationError, match="STAT_COUNT"):
        NarrativeSourceProfile.model_validate(data)


def test_bundle_rejects_equal_time_input_cycle(payload):
    data = payload["sources"][0]
    data["input_version_refs"] = [dict(object_id=data["object_id"], version=1, available_at=data["available_at"])]
    payload["sources"][0] = seal(Source.model_validate(data)).model_dump(mode="json")
    with pytest.raises(ValidationError, match="REFERENCE_CYCLE"):
        OfflineFixture.model_validate(payload)


@pytest.mark.parametrize("kind", ["FACT", "INTENT", "FORECAST", "OPINION", "RUMOR", "NARRATIVE"])
def test_claim_kinds_separate(payload, kind):
    record = Statement.model_validate({**payload["statements"][0], "claim_kind": kind})
    assert record.claim_kind == kind
    assert record.policy_certainty == "UNKNOWN"


def test_actor_topic_required_no_global_score(payload):
    data = payload["actor_topic_profiles"][0]
    first = ActorTopicProfile.model_validate(data)
    second = ActorTopicProfile.model_validate({**data, "object_id": "AP_OTHER", "topic_id": "OTHER_TOPIC"})
    assert first.actor_id == second.actor_id and first.topic_id != second.topic_id
    del data["topic_id"]
    with pytest.raises(ValidationError):
        ActorTopicProfile.model_validate(data)
    with pytest.raises(ValidationError):
        ActorTopicProfile.model_validate({**second.model_dump(), "global_score": 0.9})


def test_narrative_small_sample_unknown_no_zero_or_followers_boost(payload):
    data = payload["narrative_source_profiles"][0]
    record = NarrativeSourceProfile.model_validate(data)
    assert record.sample_n == 1 and record.originality is None and record.followers is None
    assert record.leading_stats is None and record.reliability_band == "UNKNOWN"
    popular = NarrativeSourceProfile.model_validate({**data, "followers": 10000000})
    assert popular.reliability_band == record.reliability_band
    with pytest.raises(ValidationError):
        NarrativeSourceProfile.model_validate({**data, "originality": float("nan")})
    with pytest.raises(ValidationError):
        NarrativeSourceProfile.model_validate({**data, "sample_n": "1"})


def test_zero_sample_rate_and_inconsistent_stats():
    unknown = SampleStatistic(numerator=0, denominator=0, outcome_available_at=ts(), missing_reason="尚无样本")
    assert unknown.rate is None
    for data in (dict(numerator=0, denominator=0, rate=0.0), dict(numerator=2, denominator=1, rate=1.0),
                 dict(numerator=1, denominator=2, rate=0.9)):
        with pytest.raises(ValidationError):
            SampleStatistic(outcome_available_at=ts(), **data)


def test_source_authorization_unknown_not_permission(payload):
    source = Source.model_validate(payload["sources"][0])
    assert source.terms_status == source.authorization_status == "UNKNOWN"
    assert source.allowed_uses is source.raw_retention_allowed is source.access_restrictions is None
    assert source.enabled is False


def test_version_ref_no_latest_or_coercion():
    for version in ("latest", "1", 0, True):
        with pytest.raises(ValidationError):
            VersionRef(object_id="EV_1", version=version)


def test_dna_not_stock_or_theme(payload):
    dna = payload["event_versions"][0]["dna"]
    for entities in ([], [dict(entity_id="000001", entity_type="SECURITY", name_zh="股票")],
                     [dict(entity_id="概念", entity_type="THEME", name_zh="概念股")]):
        with pytest.raises(ValidationError):
            EventDNA.model_validate({**dna, "object_entities": entities})
    with pytest.raises(ValidationError):
        EventDNA.model_validate("000001")


def test_immutability_and_extra_rejected(payload):
    source = Source.model_validate(payload["sources"][0])
    with pytest.raises(ValidationError):
        source.name_zh = "改写"
    with pytest.raises(ValidationError):
        Source.model_validate({**source.model_dump(), "portfolio_cost": 12.0})


@pytest.mark.parametrize("change,code", [("missing", "REFERENCE_MISSING"), ("duplicate", "DUPLICATE_VERSION"),
                                        ("raw", "RAW_HASH"), ("content", "CONTENT_HASH"), ("type", "REFERENCE_TYPE")])
def test_bundle_integrity(payload, change, code):
    if change == "missing":
        payload["actors"] = []
    elif change == "duplicate":
        payload["sources"].append(payload["sources"][0])
    elif change == "raw":
        payload["raw_contents"]["RAW_001"] += "被改写"
    elif change == "content":
        payload["event_versions"][0]["title_zh"] += "被改写"
    else:
        data = payload["event_versions"][0]
        data["dna"]["actor_refs"] = [data["evidence_refs"][0]]
        payload["event_versions"][0] = seal(EventVersion.model_validate(data)).model_dump(mode="json")
    with pytest.raises(ValidationError, match=code):
        OfflineFixture.model_validate(payload)
