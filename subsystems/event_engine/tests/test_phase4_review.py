from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from test_phase2_ledger import setup_ledger, obs
from test_phase4_ontology import world, draft_data, hypothesis, candidates, vr
from xevent.ledger.schema import records
from xevent.ledger.store import ref
from xevent.ontology.contracts import ImpactVariable, ImpactSpec, OntologyDraft, ImpactRuleSpec
from xevent.ontology.compatibility import normalize_impact_input, combine_impact_directions, project_legacy_record, LEGACY_POLICY, POLICY
from xevent.ontology.frozen_view import export_frozen_view, FrozenOntologyView


@pytest.mark.pit
def test_impact_identity_scope_bands_schema_roundtrip_pit(world):
    ledger, clock, engine, ontology, event, evidence = world
    cutoff = clock()
    before = ledger.replay(cutoff)
    value = engine.impact("IMPACT_REVIEW", 1, hypothesis(world, scope="TARGET_MARKET", magnitude_band="LOW",
                           start_horizon="HOURS", persistence_band="OVERNIGHT"))
    assert value.impact_id == value.object_id == "IMPACT_REVIEW"
    assert ImpactVariable.model_validate_json(value.model_dump_json()) == value
    assert {"impact_id", "scope", "magnitude_band", "start_horizon", "persistence_band"} <= ImpactVariable.model_json_schema()["properties"].keys()
    assert ledger.replay(cutoff) == before
    with pytest.raises(ValidationError, match="IMPACT_ID"):
        ImpactVariable.model_validate({**value.model_dump(), "impact_id":"OTHER"})
    later = engine.impact("IMPACT_REVIEW", 2, hypothesis(world))
    assert later.impact_id == value.impact_id
    assert (later.scope, later.magnitude_band, later.start_horizon, later.persistence_band) == ("UNKNOWN",)*4


def test_old_names_only_at_explicit_compatibility_boundary(world):
    old = hypothesis(world).model_dump()
    old["inference_type"] = old.pop("observation_kind")
    old["variable_type"] = "OUTPUT_PRICE"
    with pytest.raises(ValidationError):
        ImpactSpec.model_validate(old)
    canonical = normalize_impact_input(old)
    assert canonical.variable_type == "PRICE" and canonical.observation_kind == "HYPOTHESIS"
    assert "inference_type" not in canonical.model_dump() and "OUTPUT_PRICE" not in canonical.model_dump_json()
    with pytest.raises(ValueError, match="COMPAT_DUPLICATE"):
        normalize_impact_input({**old, "observation_kind":"OBSERVED"})
    with pytest.raises(ValidationError):
        normalize_impact_input({**old, "variable_type":"DEMAND_RISING"})


@pytest.mark.pit
def test_legacy_record_projection_never_rewrites_payload_or_time(world):
    ledger, clock, engine, ontology, event, evidence = world
    payload = hypothesis(world).model_dump(mode="json")
    for f in ("scope", "magnitude_band", "start_horizon", "persistence_band"):
        payload.pop(f)
    payload["policy_version"] = LEGACY_POLICY
    ledger._write("LEGACY_FIXTURE", "82728ab-payload", lambda conn, view, batch: ledger._put(
        conn, batch, "ImpactVariable", "OLD_IMPACT", 1, payload, [ref(event), ref(evidence)]))
    def raw_record():
        with ledger.engine.connect() as conn:
            return dict(conn.execute(select(records).where(records.c.object_id=="OLD_IMPACT", records.c.version==1)).mappings().one())
    original = raw_record()
    old = ledger.get("OLD_IMPACT", 1)
    assert old.impact_id == old.object_id and old.scope == old.start_horizon == "UNKNOWN"
    assert old.policy_version == LEGACY_POLICY
    cutoff = clock()
    before = ledger.replay(cutoff)
    new = engine.impact("OLD_IMPACT", 2, hypothesis(world, scope="ECONOMY", start_horizon="DAYS"))
    assert new.policy_version == POLICY and new.available_at > old.available_at
    assert ledger.get("OLD_IMPACT", 1).available_at == old.available_at
    assert ledger.replay(cutoff) == before and raw_record() == original


@pytest.mark.parametrize("values,expected", [(["POSITIVE"],"POSITIVE"), (["NEGATIVE"],"NEGATIVE"),
    (["POSITIVE","NEGATIVE"],"MIXED"), (["UNKNOWN"],"UNKNOWN"), (["NEUTRAL"],"NEUTRAL"),
    (["POSITIVE","UNKNOWN"],"UNKNOWN"), (["MIXED"],"MIXED")])
def test_frozen_impact_direction_semantics(values, expected):
    assert combine_impact_directions(values) == expected
    with pytest.raises(ValueError):
        combine_impact_directions(["UNCERTAIN"])


@pytest.mark.pit
def test_same_target_positive_negative_is_mixed_with_paths_retained(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    data = deepcopy(draft_data)
    data["version"] = 2
    data["rules"][1]["industry_id"] = data["rules"][0]["industry_id"]
    newer = engine.publish(OntologyDraft.model_validate(data))
    impact = engine.impact("MIXED_IMPACT", 1, hypothesis(world))
    cutoff = clock()
    before = ledger.replay(cutoff)
    result = engine.resolve(vr(impact), vr(newer), as_of=cutoff, request_key="mixed")
    assert len(result.candidate_refs) == 2 and len(result.industry_directions) == 1
    assert result.industry_directions[0].impact_direction == "MIXED"
    assert type(result).model_validate_json(result.model_dump_json()) == result
    assert ledger.replay(cutoff) == before
    unknown = engine.impact("UNKNOWN_IMPACT", 1, hypothesis(world, direction="UNKNOWN"))
    assert candidates(world, unknown, request="unknown")[0].impact_direction == "UNKNOWN"
    with pytest.raises(ValidationError):
        ImpactRuleSpec.model_validate({**data["rules"][0], "impact_direction":"UNCERTAIN"})


def make_theme(world):
    ledger, clock, engine, ontology, event, evidence = world
    return engine.theme("COMPAT_THEME", 1, event_ref=vr(event), canonical_name_zh="算力电力",
                        description_zh="关联不是经济暴露", evidence_refs=[vr(evidence)])


@pytest.mark.pit
def test_frozen_view_roundtrip_later_theme_relation_and_crosswalk(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    theme = make_theme(world)
    cutoff = clock()
    initial = export_frozen_view(engine, vr(theme), vr(ontology), as_of=cutoff)
    before = ledger.replay(cutoff)
    assert not initial.theme.related_industry_refs
    assert initial.theme.association_evidence_refs == (vr(evidence),)
    target = next(r for r in ontology.segment_refs if r.object_id=="XIND_COPPER_MINING")
    relation = engine.theme_relation("THEME_RELATION", 1, theme_ref=vr(theme), ontology_ref=vr(ontology), industry_ref=target,
        evidence_refs=[vr(evidence)], mechanism_zh="仅记录人工叙事关联，不证明经济暴露")
    current_cutoff = clock()
    current = export_frozen_view(engine, vr(theme), vr(ontology), as_of=current_cutoff)
    assert current.theme.related_industry_refs == (target,)
    assert current.theme.economic_path_status == "UNRESOLVED"
    restored = FrozenOntologyView.model_validate_json(current.model_dump_json()).normalized()
    assert restored["theme"] == theme and restored["relations"] == (relation,)
    assert any(s.external_crosswalks for s in current.segments)
    assert restored["crosswalks"][0].external_code == "000001"
    assert export_frozen_view(engine, vr(theme), vr(ontology), as_of=current_cutoff) == current
    assert export_frozen_view(engine, vr(theme), vr(ontology), as_of=cutoff) == initial
    data = deepcopy(draft_data)
    data["version"] = 2
    data["crosswalks"][0]["x_industry_id"] = "XIND_COPPER_USERS"
    newer = engine.publish(OntologyDraft.model_validate(data))
    new_view = export_frozen_view(engine, vr(theme), vr(newer), as_of=clock())
    assert not new_view.theme.related_industry_refs  # 不把旧本体关系动态套到新产业版本。
    assert export_frozen_view(engine, vr(theme), vr(ontology), as_of=cutoff) == initial
    assert ledger.replay(cutoff) == before
    assert FrozenOntologyView.model_validate_json(new_view.model_dump_json()).normalized()["crosswalks"][0].x_industry_id == "XIND_COPPER_USERS"
    engine.theme_relation("THEME_RELATION", 2, theme_ref=vr(theme), ontology_ref=vr(ontology), industry_ref=None,
        evidence_refs=[vr(evidence)], mechanism_zh="后来复核无法确认关联")
    assert not export_frozen_view(engine, vr(theme), vr(ontology), as_of=clock()).theme.related_industry_refs
    assert export_frozen_view(engine, vr(theme), vr(ontology), as_of=current_cutoff) == current


def test_frozen_view_rejects_drifting_duplicate_projection(world):
    ledger, clock, engine, ontology, event, evidence = world
    theme = make_theme(world)
    result = export_frozen_view(engine, vr(theme), vr(ontology), as_of=clock())
    data = result.model_dump()
    data["theme"]["association_evidence_refs"] = []
    with pytest.raises(ValidationError, match="FROZEN_PROJECTION"):
        FrozenOntologyView.model_validate(data)
    data = result.model_dump()
    next(s for s in data["segments"] if s["external_crosswalks"])["external_crosswalks"] = []
    with pytest.raises(ValidationError, match="FROZEN_PROJECTION"):
        FrozenOntologyView.model_validate(data)
    assert FrozenOntologyView.model_json_schema()["type"] == "object"


def test_uncertain_projection_is_restricted_to_known_legacy_policy(draft_data):
    raw = {**draft_data["rules"][0], "policy_version":LEGACY_POLICY, "impact_direction":"UNCERTAIN"}
    for kind in ("IndustryImpactRule", "IndustryImpactCandidate"):
        assert project_legacy_record(kind, raw, "OLD")["impact_direction"] == "UNKNOWN"
        current = {**raw, "policy_version":POLICY}
        assert project_legacy_record(kind, current, "CURRENT")["impact_direction"] == "UNCERTAIN"
    assert raw["impact_direction"] == "UNCERTAIN"  # 读取投影不修改原payload。
    with pytest.raises(ValidationError):
        ImpactRuleSpec.model_validate({**draft_data["rules"][0], "impact_direction":"UNCERTAIN"})


@pytest.mark.pit
def test_roundtrip_preserves_additional_relation_evidence(world, setup_ledger):
    ledger, clock, engine, ontology, event, evidence = world
    source, seed = setup_ledger[2:]
    observation = obs(clock, source, "另行说明的主题关联证据", claim_kind="NARRATIVE")
    association = ledger.ingest(observation.model_copy(update={"locator":"fixture:relation-evidence"}), seed)
    event = ledger.history(as_of=clock(), kind="EventVersion")[-1]
    # Phase2单次摄取版本仅引用本次材料；复用Phase3显式重算得到汇集证据的事件版本。
    from xevent.states.engine import StateEngine
    states = StateEngine(ledger)
    policy = states.policy()
    snapshot = states.evaluate(vr(event), vr(policy), request_key="fixture-event-evidence", as_of=clock())
    event = ledger.get(snapshot.event_ref.object_id, snapshot.event_ref.version)
    theme = engine.theme("EXTRA_EVIDENCE_THEME", 1, event_ref=vr(event), canonical_name_zh="算力电力",
        description_zh="关联原文与初始主题证据分离", evidence_refs=[vr(evidence)])
    cutoff = clock()
    old = export_frozen_view(engine, vr(theme), vr(ontology), as_of=cutoff)
    relation = engine.theme_relation("EXTRA_RELATION", 1, theme_ref=vr(theme), ontology_ref=vr(ontology),
        industry_ref=ontology.segment_refs[0], evidence_refs=[vr(association)], mechanism_zh="仅叙事关联")
    current = export_frozen_view(engine, vr(theme), vr(ontology), as_of=clock())
    assert set(current.theme.association_evidence_refs) == {vr(evidence), vr(association)}
    normalized = FrozenOntologyView.model_validate_json(current.model_dump_json()).normalized()
    assert normalized["theme"].evidence_refs == (vr(evidence),)
    assert normalized["relations"] == (relation,) and relation.evidence_refs == (vr(association),)
    assert export_frozen_view(engine, vr(theme), vr(ontology), as_of=cutoff) == old
    with pytest.raises(ValidationError, match="PIT_FROZEN_VIEW"):
        FrozenOntologyView.model_validate({**current.model_dump(), "as_of":cutoff})
