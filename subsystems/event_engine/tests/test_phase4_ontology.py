from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from test_phase2_ledger import setup_ledger, obs
from xevent.contracts.common import VersionRef
from xevent.ledger.store import Ledger, ref
from xevent.ontology.contracts import (ImpactSpec, OntologyDraft, IndustrySegment,
    normalize_impact_phrase, SCHEMAS)
from xevent.ontology.engine import OntologyEngine


FIXTURE = Path(__file__).parents[1] / "configs" / "phase4_ontology.zh-CN.json"


def vr(obj):
    return VersionRef(**ref(obj))


@pytest.fixture
def draft_data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["ontology"]


@pytest.fixture
def world(setup_ledger, draft_data):
    ledger, clock, source, seed = setup_ledger
    evidence = ledger.ingest(obs(clock, source, "虚构公告：明确宣布铜供应减少", claim_kind="FACT", is_first_hand=True), seed)
    event = ledger.history(as_of=clock(), kind="EventVersion")[-1]
    engine = OntologyEngine(ledger)
    ontology = engine.publish(OntologyDraft.model_validate(draft_data))
    return ledger, clock, engine, ontology, event, evidence


def spec(world, **changes):
    ledger, clock, engine, ontology, event, evidence = world
    data = dict(event_ref=ref(event), variable_type="SUPPLY", target_object="COPPER", direction="DOWN",
        geography="GLOBAL", observation_kind="OBSERVED", evidence_refs=[ref(evidence)], mechanism_zh="原始公告宣布供应变化",
        observation_basis=dict(evidence_ref=ref(evidence), quoted_span="明确宣布铜供应减少",
            reviewed_by="虚构核验者", interpretation_zh="仅观察宣布减产，不推断已执行", scope="ANNOUNCED_CHANGE"))
    return ImpactSpec.model_validate({**data, **changes})


def hypothesis(world, **changes):
    return spec(world, **{**dict(variable_type="PRICE", direction="UP", observation_kind="HYPOTHESIS",
        observation_basis=None, premise_refs=[ref(world[5])], uncertainty_zh="需求或库存可能抵消供应变化"), **changes})


def candidates(world, impact, *, ontology=None, as_of=None, request="resolve"):
    ledger, clock, engine, current, event, evidence = world
    result = engine.resolve(vr(impact), vr(ontology or current), as_of=as_of or clock(), request_key=request)
    return [ledger.get(r.object_id, r.version) for r in result.candidate_refs]


@pytest.mark.parametrize("phrase", ["DEMAND_INCREASE", "STRONGER_DEMAND", "DEMAND_RISING", "需求增长"])
def test_demand_has_one_canonical_representation(world, phrase):
    fields = normalize_impact_phrase(phrase)
    assert fields == dict(variable_type="DEMAND", direction="UP")
    assert spec(world, **fields).variable_type == "DEMAND"
    with pytest.raises(ValidationError):
        spec(world, variable_type=phrase)


@pytest.mark.parametrize("fields", [dict(variable_type="OUTPUT_PRICE"), dict(direction="INCREASE"),
    dict(target_object="任意概念股"), dict(geography="ANYWHERE"), dict(observation_kind="SOURCE_FACT"),
    dict(confidence="CERTAIN"), dict(validation_status="TRUST_ME")])
def test_unknown_internal_classifications_rejected(world, fields):
    with pytest.raises(ValidationError):
        spec(world, **fields)


@pytest.mark.parametrize("bad", [dict(fx_pair=None), dict(direction="UNKNOWN"), dict(currency="USD"),
    dict(fx_pair=dict(base="CNY", quote="CNY")), dict(unit="UNKNOWN"), dict(target_object="COPPER")])
def test_fx_pair_direction_and_quote_required(world, bad):
    fields = dict(variable_type="FX", target_object="CURRENCY", direction="UP", currency="CNY",
                  fx_pair=dict(base="USD", quote="CNY"), unit="FX_RATE")
    with pytest.raises(ValidationError):
        spec(world, **{**fields, **bad})


def test_fx_canonical_pair_roundtrip(world):
    value = spec(world, variable_type="FX", target_object="CURRENCY", direction="UP", currency="CNY",
                 fx_pair=dict(base="USD", quote="CNY"), unit="FX_RATE")
    assert ImpactSpec.model_validate_json(value.model_dump_json()) == value
    assert normalize_impact_phrase("人民币贬值") is None


def test_supply_observed_and_price_hypothesis_are_separate(world):
    engine = world[2]
    supply = engine.impact("SUPPLY", 1, spec(world))
    price = engine.impact("PRICE", 1, hypothesis(world, premise_refs=[ref(supply)]))
    assert (supply.variable_type, supply.direction, supply.observation_kind) == ("SUPPLY", "DOWN", "OBSERVED")
    assert (price.variable_type, price.direction, price.observation_kind) == ("PRICE", "UP", "HYPOTHESIS")
    assert price.premise_refs == (vr(supply),) and price.uncertainty_zh
    assert price.available_at >= supply.available_at


@pytest.mark.parametrize("change", [dict(premise_refs=[]), dict(uncertainty_zh=None), dict(validation_status="VERIFIED"),
    dict(observation_kind="OBSERVED"), dict(observation_kind="OBSERVED", observation_basis=None)])
def test_hypothesis_cannot_masquerade_as_observation(world, change):
    with pytest.raises(ValidationError):
        hypothesis(world, **change)


@pytest.mark.parametrize("claim", ["NARRATIVE", "RUMOR", "FORECAST", "INTENT"])
def test_non_fact_raw_material_cannot_be_observed(world, setup_ledger, claim):
    ledger, clock, engine, ontology, event, evidence = world
    source, seed = setup_ledger[2:]
    new = ledger.ingest(obs(clock, source, "明确宣布铜供应减少", version="2", change_type="EDIT", claim_kind=claim), seed)
    latest = ledger.history(as_of=clock(), kind="EventVersion")[-1]
    with pytest.raises(ValueError, match="OBSERVED_FACT"):
        engine.impact("NON_FACT", 1, spec((ledger, clock, engine, ontology, latest, new)))


def test_observed_quote_and_chinese_mechanism_required(world):
    value = spec(world)
    data = value.model_dump()
    data["observation_basis"]["quoted_span"] = "原文没有此句"
    with pytest.raises(ValueError, match="OBSERVED_QUOTE"):
        world[2].impact("FAKE_QUOTE", 1, ImpactSpec.model_validate(data))
    for mechanism in ("", " ", "only english"):
        with pytest.raises(ValidationError):
            spec(world, mechanism_zh=mechanism)


@pytest.mark.parametrize("kind", ["cycle", "dangling", "level", "duplicate", "interval"])
def test_industry_tree_rejects_invalid_structure(draft_data, kind):
    data = deepcopy(draft_data)
    if kind == "cycle":
        data["segments"][0]["parent_id"] = "XIND_COPPER_MINING"
    elif kind == "dangling":
        data["segments"][1]["parent_id"] = "XIND_MISSING"
    elif kind == "level":
        data["segments"][1]["level"] = 7
    elif kind == "duplicate":
        data["segments"].append(data["segments"][0])
    else:
        data["segments"][0]["effective_to"] = "2025-01-01T00:00:00Z"
    with pytest.raises(ValidationError):
        OntologyDraft.model_validate(data)


@pytest.mark.pit
def test_late_alias_never_backfills_old_asof(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    clock.value = clock.value.replace(hour=10, minute=0, second=0, microsecond=0)
    assert engine.resolve_alias("上游铜资源", as_of=clock()).mapping_status == "UNRESOLVED"
    cutoff = clock.value.replace(minute=30)
    old = engine.resolve_alias("上游铜资源", as_of=cutoff)
    before = ledger.replay(cutoff)
    clock.value = clock.value.replace(hour=11)
    data = {**draft_data, "version":2, "aliases":[dict(alias_id="upstream", phrase="上游铜资源", industry_id="XIND_COPPER_MINING")]}
    newer = engine.publish(OntologyDraft.model_validate(data))
    assert engine.resolve_alias("上游铜资源", as_of=cutoff) == old
    assert ledger.replay(cutoff) == before
    assert engine.resolve_alias("上游铜资源", as_of=clock.value.replace(minute=30)).mapping_status == "MATCHED"
    assert engine.resolve_alias("上游铜资源", ontology_ref=vr(ontology), as_of=clock()).mapping_status == "UNRESOLVED"
    with pytest.raises(ValueError):
        engine.resolve_alias("上游铜资源", ontology_ref=vr(newer), as_of=cutoff)


@pytest.mark.pit
def test_crosswalk_changes_are_append_only(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    old = engine.crosswalk("fixture-000001", vr(ontology), as_of=clock())
    assert old.external_code == "000001"
    cutoff = clock()
    before = ledger.replay(cutoff)
    data = deepcopy(draft_data)
    data["version"] = 2
    data["crosswalks"][0]["x_industry_id"] = "XIND_COPPER_USERS"
    newer = engine.publish(OntologyDraft.model_validate(data))
    new = engine.crosswalk("fixture-000001", vr(newer), as_of=clock())
    assert new.object_id == old.object_id and new.version == old.version+1
    assert new.x_industry_id != old.x_industry_id
    assert ledger.get(old.object_id, old.version) == old
    assert ledger.replay(cutoff) == before


def test_narrative_theme_cannot_be_industry_or_impact(world, setup_ledger):
    ledger, clock, engine, ontology, event, evidence = world
    theme = engine.theme("THEME", 1, event_ref=vr(event), canonical_name_zh="人形机器人",
                         description_zh="仅叙事主题", evidence_refs=[vr(evidence)])
    assert theme.economic_path_status == "UNRESOLVED"
    with pytest.raises(ValidationError):
        IndustrySegment.model_validate(theme.model_dump())
    with pytest.raises(ValueError, match="ONTOLOGY_REFERENCE"):
        engine.resolve(vr(theme), vr(ontology), as_of=clock(), request_key="bad-theme")
    source, seed = setup_ledger[2:]
    narrative = ledger.ingest(obs(clock, source, "算力电力叙事", version="2", change_type="EDIT", claim_kind="NARRATIVE"), seed)
    latest = ledger.history(as_of=clock(), kind="EventVersion")[-1]
    value = hypothesis((ledger, clock, engine, ontology, latest, narrative))
    impact = engine.impact("THEME_HYPOTHESIS", 1, value)
    resolved = candidates(world, impact)
    assert len(resolved) == 1 and resolved[0].mapping_status == "UNRESOLVED" and resolved[0].industry_ref is None


def semantic_output(values):
    return [(c.industry_ref, c.impact_direction, c.path_role, c.mapping_status, c.mechanism_zh, c.observation_kind) for c in values]


@pytest.mark.pit
def test_positive_negative_candidates_determinism_and_old_ontology(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    impact = engine.impact("COPPER_PRICE", 1, hypothesis(world))
    cutoff = clock()
    a = candidates(world, impact, as_of=cutoff, request="first")
    assert {c.impact_direction for c in a} == {"POSITIVE", "NEGATIVE"}
    assert all(c.mapping_status == "CANDIDATE" and c.observation_kind == "HYPOTHESIS" for c in a)
    assert candidates(world, impact, as_of=cutoff, request="first") == a
    assert semantic_output(candidates(world, impact, as_of=cutoff, request="second")) == semantic_output(a)
    replay_at = clock()
    before = ledger.replay(replay_at)
    data = deepcopy(draft_data)
    data["version"] = 2
    data["rules"] = data["rules"][:1]
    newer = engine.publish(OntologyDraft.model_validate(data))
    assert len(candidates(world, impact, ontology=newer, request="new")) == 1
    assert semantic_output(candidates(world, impact, as_of=cutoff, request="old-again")) == semantic_output(a)
    assert ledger.replay(replay_at) == before


@pytest.mark.parametrize("bucket", ["rules", "crosswalks"])
def test_mapping_cannot_be_verified_without_evidence(world, draft_data, bucket):
    data = deepcopy(draft_data)
    data[bucket][0]["mapping_status"] = "VERIFIED"
    data[bucket][0]["reviewed_by"] = "核验者"
    with pytest.raises(ValidationError, match="MAPPING_PROOF"):
        OntologyDraft.model_validate(data)


def test_stable_ids_cannot_be_reused_for_different_role(world, draft_data):
    data = deepcopy(draft_data)
    data["version"] = 2
    data["segments"][1]["economic_role"] = "SERVICE"
    with pytest.raises(ValueError, match="INDUSTRY_STABLE_ID"):
        world[2].publish(OntologyDraft.model_validate(data))


@pytest.mark.pit
def test_pit_effective_date_is_not_knowledge_time(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    past = ontology.available_at - timedelta(seconds=1)
    assert engine.resolve_alias("铜矿生产", as_of=past).mapping_status == "UNRESOLVED"
    data = deepcopy(draft_data)
    data["version"] = 2
    data["segments"][1]["effective_from"] = (clock.value+timedelta(days=1)).isoformat()
    newer = engine.publish(OntologyDraft.model_validate(data))
    assert engine.resolve_alias("铜矿生产", ontology_ref=vr(newer), as_of=clock()).mapping_status == "UNRESOLVED"


@pytest.mark.pit
@pytest.mark.parametrize("stage", ["after_ontology", "after_commit"])
def test_ontology_atomicity_and_recovery(world, draft_data, stage):
    ledger, clock, engine, ontology, event, evidence = world
    cutoff = clock()
    before = ledger.replay(cutoff)
    draft = OntologyDraft.model_validate({**draft_data, "version":2})
    def crash(point):
        if point == stage:
            raise RuntimeError("模拟本体发布中断")
    ledger.fault = crash
    with pytest.raises(RuntimeError):
        engine.publish(draft)
    recovered = Ledger(ledger.path, clock=clock)
    try:
        out = OntologyEngine(recovered).publish(draft)
        assert out.version == 2
        assert recovered.replay(cutoff) == before
        assert len(recovered.history(as_of=clock(), kind="OntologyVersion")) == 2
    finally:
        recovered.close()


@pytest.mark.pit
def test_phase4_never_modifies_event_or_three_states(world):
    ledger, clock, engine, ontology, event, evidence = world
    kinds = ("EventVersion", "EventStateSnapshot", "StateTransition", "EventClock", "RecomputeTrigger")
    before = {k:ledger.history(as_of=clock(), kind=k) for k in kinds}
    impact = engine.impact("PRICE", 1, hypothesis(world))
    candidates(world, impact)
    engine.theme("THEME", 1, event_ref=vr(event), canonical_name_zh="算力电力", description_zh="只属主题", evidence_refs=[vr(evidence)])
    assert {k:ledger.history(as_of=clock(), kind=k) for k in kinds} == before
    for obj in ledger.history(as_of=clock()):
        assert type(obj).model_validate_json(obj.model_dump_json()) == obj


@pytest.mark.parametrize("model", SCHEMAS)
def test_phase4_json_schema(model):
    assert SCHEMAS[model].model_json_schema()["type"] == "object"


def test_phase4_chinese_cli_fixture(tmp_path, capsys):
    from xevent.cli import main
    args = ["ontology-fixture", "--db", str(tmp_path/"demo.sqlite"), "--fixture", str(FIXTURE)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["晚到别名"] == {"10:30回放":"UNRESOLVED", "11:30解析":"MATCHED"}
    assert {c["影响"] for c in result["产业候选"]} == {"POSITIVE", "NEGATIVE"}
    assert result["事件状态"] == "未修改"
    assert main(args) == 2
    assert main(["schema", "--model", "ImpactVariable"]) == 0


def test_fx_resolver_does_not_confuse_inverse_pair(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    data = deepcopy(draft_data)
    data["version"] = 2
    data["rules"] = [{**data["rules"][0], "variable_type":"FX", "target_object":"CURRENCY",
                      "fx_pair":dict(base="USD", quote="CNY"), "mechanism_zh":"虚构特定币种报价路径，仅作方向校验"}]
    newer = engine.publish(OntologyDraft.model_validate(data))
    for n, (base, quote, expected) in enumerate((("USD", "CNY", "CANDIDATE"), ("CNY", "USD", "UNRESOLVED"))):
        impact = engine.impact(f"FX{n}", 1, hypothesis(world, variable_type="FX", target_object="CURRENCY",
            unit="FX_RATE", currency=quote, fx_pair=dict(base=base, quote=quote)))
        assert candidates(world, impact, ontology=newer, request=f"fx-{n}")[0].mapping_status == expected


def test_premise_hold_and_raw_provenance_cannot_be_laundered(world):
    ledger, clock, engine, ontology, event, evidence = world
    premise = engine.impact("HELD", 1, hypothesis(world, validation_status="HOLD"))
    impact = engine.impact("DOWNSTREAM", 1, hypothesis(world, premise_refs=[ref(premise)], evidence_refs=[]))
    outputs = candidates(world, impact)
    assert {c.mapping_status for c in outputs} == {"HOLD"}
    assert all(vr(evidence) in c.evidence_refs for c in outputs)


def test_ambiguous_alias_is_unresolved(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    data = {**draft_data, "version":2, "aliases":[
        dict(alias_id="ambiguous-a", phrase="铜产业", industry_id="XIND_COPPER_MINING"),
        dict(alias_id="ambiguous-b", phrase="铜产业", industry_id="XIND_COPPER_USERS")]}
    engine.publish(OntologyDraft.model_validate(data))
    result = engine.resolve_alias("铜产业", as_of=clock())
    assert result.mapping_status == "UNRESOLVED" and result.industry_ref is None and len(result.alias_refs) == 2


@pytest.mark.pit
def test_unresolved_crosswalk_and_old_version_are_explicit(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    cutoff = clock()
    data = deepcopy(draft_data)
    data["version"] = 2
    data["crosswalks"][0].update(x_industry_id=None, mapping_type="UNRESOLVED", mapping_status="UNRESOLVED")
    newer = engine.publish(OntologyDraft.model_validate(data))
    value = engine.crosswalk("fixture-000001", vr(newer), as_of=clock())
    assert value.industry_ref is None and value.mapping_status == "UNRESOLVED"
    assert engine.crosswalk("fixture-000001", vr(ontology), as_of=cutoff).industry_ref is not None


@pytest.mark.pit
def test_late_impact_and_mapping_not_visible_at_old_cutoff(world):
    ledger, clock, engine, ontology, event, evidence = world
    old = engine.impact("REVISION", 1, hypothesis(world))
    cutoff = clock()
    before = ledger.replay(cutoff)
    new = engine.impact("REVISION", 2, hypothesis(world, direction="DOWN"))
    with pytest.raises(ValueError, match="ONTOLOGY_REFERENCE"):
        candidates(world, new, as_of=cutoff, request="future")
    later = candidates(world, new, request="now")
    assert later[0].mapping_status == "UNRESOLVED"
    assert ledger.get(old.object_id, old.version) == old
    assert ledger.replay(cutoff) == before
    assert all(c.available_at >= max(new.available_at, c.computed_at, c.recorded_at) for c in later)


@pytest.mark.pit
def test_resolution_rollback_has_no_partial_candidates(world):
    ledger, clock, engine, ontology, event, evidence = world
    impact = engine.impact("ROLLBACK", 1, hypothesis(world))
    cutoff = clock()
    before = ledger.replay(cutoff)
    def crash(stage):
        if stage == "after_industry_resolution":
            raise RuntimeError("模拟候选发布中断")
    ledger.fault = crash
    with pytest.raises(RuntimeError):
        candidates(world, impact, as_of=cutoff)
    assert ledger.replay(clock()) == before
    ledger.fault = lambda stage: None
    assert len(candidates(world, impact, as_of=cutoff)) == 2


def test_verified_rule_still_outputs_hypothesis_candidate(world, draft_data):
    ledger, clock, engine, ontology, event, evidence = world
    data = deepcopy(draft_data)
    data["version"] = 2
    for rule in data["rules"]:
        rule.update(mapping_status="VERIFIED", reviewed_by="虚构核验者", evidence_refs=[ref(evidence)])
    newer = engine.publish(OntologyDraft.model_validate(data))
    impact = engine.impact("VERIFIED_RULE_INPUT", 1, hypothesis(world))
    assert all(c.mapping_status == "CANDIDATE" and c.observation_kind == "HYPOTHESIS"
               for c in candidates(world, impact, ontology=newer))


@pytest.mark.parametrize("field", ["parent_id", "industry_id"])
def test_theme_name_cannot_be_used_as_industry_identity(draft_data, field):
    data = deepcopy(draft_data)
    data["segments"][1][field] = "人形机器人"
    with pytest.raises(ValidationError):
        OntologyDraft.model_validate(data)
