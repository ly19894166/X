"""PR #19人工Review：触发与事实裁定分离、合源重算、按维度溯源。"""
from datetime import timedelta

import pytest

from test_phase2_ledger import setup_ledger, obs
from test_phase3_states import world, receive, assess, evaluate, latest, vr
from xevent.contracts import Source, NarrativeSourceProfile
from xevent.contracts.common import ObservationWindow
from xevent.ledger.contracts import EventSeed, RawObservation
from xevent.ledger.store import Ledger, ref
from xevent.states.engine import StateEngine


def refs(items):
    return {(r.object_id, r.version) for r in items}


def transitions(ledger, snapshot):
    return {t.dimension: t for r in snapshot.transition_refs for t in [ledger.get(r.object_id, r.version)]}


@pytest.mark.pit
@pytest.mark.parametrize("first_hand", [False, True])
def test_verified_r5_requires_explicit_semantic_assessment(world, first_hand):
    ledger, clock, source, seed, engine, policy = world
    initial = receive(world, "已经核验的支持", claim_kind="FACT", is_first_hand=True)
    support = assess(world, initial, "SUPPORT")
    assert evaluate(world, "supported", assessment_refs=[vr(support)]).fact_state == "PLAUSIBLE"
    evidence = receive(world, "可能的反证尚待语义核验", locator="fixture:counter", claim_kind="FACT", is_first_hand=first_hand)
    # 测试StateEngine的版本化R5输入边界，不改变Phase2仅对一手结构化撤回分类的规则。
    ledger._write("FIXTURE_R5", "fixture-r5", lambda conn, view, batch: ledger._put(
        conn, batch, "NoveltyDecision", "FIXTURE_R5", 1,
        dict(classification="R5", evidence_ref=ref(evidence), reason_codes=["离线R5边界fixture"]), [ref(evidence)]))
    state = evaluate(world, "r5-not-assessed")
    assert state.fact_state == "PLAUSIBLE" and state.priority == "P0"
    fact = transitions(ledger, state)["FACT"]
    assert fact.outcome == "HOLD" and vr(evidence) not in fact.evidence_refs
    assert any(t.priority == "P0" and "R5_COUNTEREVIDENCE" in t.trigger_reasons
               and t.dispatch == "READY" for t in engine.pending(as_of=clock()))
    cutoff = clock()
    before = ledger.replay(cutoff)
    counter = assess(world, evidence, "COUNTEREVIDENCE")
    after = evaluate(world, "explicit-counter", assessment_refs=[vr(counter)])
    assert after.fact_state == "CONTRADICTED"
    assert vr(evidence) in transitions(ledger, after)["FACT"].evidence_refs
    assert ledger.replay(cutoff) == before


def independent_pair(world):
    ledger, clock, source, seed, engine, policy = world
    first = receive(world, "独立支持A", claim_kind="FACT", is_first_hand=True)
    a = assess(world, first, "SUPPORT", "a")
    other = ledger.register_source(Source.model_validate({**source.model_dump(), "source_id": "SECOND", "object_id": "SECOND"}))
    second = ledger.ingest(obs(clock, other, "独立支持B", claim_kind="FACT", is_first_hand=True), seed)
    b = assess(world, second, "SUPPORT", "b")
    state = evaluate(world, "two-independent", assessment_refs=[vr(a), vr(b)])
    assert state.fact_state == "INDEPENDENTLY_CONFIRMED"
    proof_span = f"{first.source_id} {first.canonical_url_or_locator} 与 {second.source_id} {second.canonical_url_or_locator} 实为同源"
    proof_seed = EventSeed(**{**seed.model_dump(), "event_id": "PROOF_EVENT"})
    proof = ledger.ingest(RawObservation.model_validate({**obs(clock, source, proof_span).model_dump(),
                         "locator": "fixture:proof"}), proof_seed)
    return first, second, dict(confirmation_key="review-confirm", confirmation_ref=vr(proof), proof_span=proof_span)


@pytest.mark.pit
def test_later_origin_confirmation_queues_immediate_recompute_and_preserves_asof(world):
    ledger, clock, source, seed, engine, policy = world
    first, second, kwargs = independent_pair(world)
    linked_seed = EventSeed(**{**seed.model_dump(), "event_id": "LINKED_EVENT"})
    ledger.ingest(RawObservation.model_validate({**obs(clock, source, "另一事件引用同根", origin_ref=vr(first)).model_dump(),
                  "locator": "fixture:linked"}), linked_seed)
    event = latest(ledger, clock)
    ledger._write("NARRATIVE_FIXTURE", "cooldown-fixture", lambda conn, view, batch: engine._trigger(
        conn, view, batch, ref(event), ["NARRATIVE_ACCELERATION"], "P2", clock(), policy, [ref(event), ref(policy)]))
    ordinary = next(t for t in engine.pending(as_of=clock()) if t.trigger_reasons == ("NARRATIVE_ACCELERATION",))
    cutoff = clock()
    before = ledger.replay(cutoff)
    old_count = ledger.origin_summary(as_of=cutoff, event_id=seed.event_id)
    for _ in range(2):
        ledger.confirm_origin([first.origin_cluster_id, second.origin_cluster_id], [vr(first), vr(second)], **kwargs)
    tasks = [t for t in engine.pending(as_of=clock()) if "ORIGIN_RELATION_CHANGE" in t.trigger_reasons]
    assert {t.event_ref.object_id for t in tasks} == {seed.event_id, linked_seed.event_id}
    assert len(tasks) == 2
    task = next(t for t in tasks if t.event_ref.object_id == seed.event_id)
    assert task.priority == "P1" and task.dispatch == "READY" and task.cooldown_parent_ref is None
    assert task.not_before < ordinary.available_at + timedelta(seconds=policy.rules.cooldown_seconds)
    cluster = next(c for c in ledger.history(as_of=clock(), kind="OriginClusterVersion") if c.basis == "CONFIRMED_SAME_ORIGIN")
    assert refs([cluster]) <= refs(task.input_version_refs) and task.available_at >= cluster.available_at > cutoff
    assert ledger.replay(cutoff) == before
    assert ledger.origin_summary(as_of=cutoff, event_id=seed.event_id) == old_count
    assert old_count["independent_source_count"] == 2
    state = evaluate(world, "after-merge")
    fact = transitions(ledger, state)["FACT"]
    summary = ledger.get(fact.origin_source_summary_ref.object_id, fact.origin_source_summary_ref.version)
    assert summary.independent_source_count == summary.origin_count == 1
    assert fact.new_state == "CONTRADICTED" and fact.outcome == "HOLD"
    assert refs(summary.evidence_refs) == refs([first, second])
    assert refs(summary.source_refs) == refs([first.source_ref, second.source_ref])
    assert vr(cluster) in summary.cluster_refs
    assert ledger.replay(cutoff) == before
    # 再确认相同关系可追加审计版本，但不得制造新的关系变化任务。
    ledger.confirm_origin([first.origin_cluster_id, second.origin_cluster_id], [vr(first), vr(second)],
                          **{**kwargs, "confirmation_key": "same-relation-again"})
    assert len([t for t in engine.pending(as_of=clock()) if "ORIGIN_RELATION_CHANGE" in t.trigger_reasons]) == 2


@pytest.mark.pit
@pytest.mark.parametrize("stage", ["after_origin_confirmation", "after_commit"])
def test_origin_confirmation_task_atomic_recovery(world, stage):
    ledger, clock, source, seed, engine, policy = world
    first, second, kwargs = independent_pair(world)
    cutoff = clock()
    before = ledger.replay(cutoff)
    def fault(point):
        if point == stage:
            raise RuntimeError("合源事务故障fixture")
    ledger.fault = fault
    with pytest.raises(RuntimeError, match="合源事务故障"):
        ledger.confirm_origin([first.origin_cluster_id, second.origin_cluster_id], [vr(first), vr(second)], **kwargs)
    assert ledger.replay(cutoff) == before
    restarted = Ledger(ledger.path, clock=clock)
    restarted.confirm_origin([first.origin_cluster_id, second.origin_cluster_id], [vr(first), vr(second)], **kwargs)
    tasks = [t for t in StateEngine(restarted).pending(as_of=clock()) if "ORIGIN_RELATION_CHANGE" in t.trigger_reasons]
    assert len(tasks) == 1
    assert len([c for c in restarted.history(as_of=clock(), kind="OriginClusterVersion") if c.basis == "CONFIRMED_SAME_ORIGIN"]) == 1
    assert restarted.replay(cutoff) == before


@pytest.mark.pit
def test_dimension_provenance_and_support_summary_share_exact_subset(world):
    ledger, clock, source, seed, engine, policy = world
    fact_evidence = receive(world, "事实主张", claim_kind="FACT", is_first_hand=True)
    support = assess(world, fact_evidence, "SUPPORT")
    other = ledger.register_source(Source.model_validate({**source.model_dump(), "source_id": "PRICE_SOURCE", "object_id": "PRICE_SOURCE"}))
    price_evidence = ledger.ingest(obs(clock, other, "离线价格数据", claim_kind="NARRATIVE"), seed)
    unrelated = receive(world, "历史无关传闻", locator="fixture:unrelated", claim_kind="RUMOR")
    clock.advance(hours=3)
    prior_window = receive(world, "前窗传播", locator="fixture:prior", claim_kind="RUMOR")
    clock.advance(minutes=61)
    narrative_evidence = receive(world, "当前传播", locator="fixture:current", claim_kind="NARRATIVE")
    price = engine.price(vr(latest(ledger, clock)), observation_key="review-price", security_id="000001",
        window=ObservationWindow(start=clock.value-timedelta(minutes=1), end=clock()),
        observation="INITIAL_REACTION", evidence_refs=[vr(price_evidence)], basis_zh="离线fixture")
    state = evaluate(world, "dimension-inputs", assessment_refs=[vr(support)], price_refs=[vr(price)])
    dims = transitions(ledger, state)
    assert refs(dims["FACT"].evidence_refs) == refs([fact_evidence])
    assert refs(dims["PRICING"].evidence_refs) == refs([price_evidence])
    assert refs(dims["NARRATIVE"].evidence_refs) == refs([prior_window, narrative_evidence])
    for transition in dims.values():
        assert vr(unrelated) not in transition.evidence_refs
        assert refs([unrelated]) <= refs(transition.input_version_refs)
    summary = ledger.get(dims["FACT"].origin_source_summary_ref.object_id, dims["FACT"].origin_source_summary_ref.version)
    assert refs(summary.evidence_refs) == refs([fact_evidence])
    assert refs(summary.source_refs) == refs([fact_evidence.source_ref])
    assert summary.origin_count == summary.independent_source_count == 1
    clusters = [ledger.get(r.object_id, r.version) for r in summary.cluster_refs]
    assert clusters and all(fact_evidence.origin_cluster_id in c.member_origin_ids for c in clusters)
    price_summary = ledger.history(as_of=clock(), kind="EventPriceSummary")[-1]
    assert refs(price_summary.evidence_refs) == refs([price_evidence])


def test_no_support_has_no_origin_summary_provenance(world):
    ledger, clock, source, seed, engine, policy = world
    receive(world, "未核验一手材料", is_first_hand=True)
    state = evaluate(world, "no-support")
    fact = transitions(ledger, state)["FACT"]
    summary = ledger.get(fact.origin_source_summary_ref.object_id, fact.origin_source_summary_ref.version)
    assert not summary.evidence_refs and not summary.source_refs and not summary.cluster_refs
    assert summary.origin_count == 0 and not fact.evidence_refs


@pytest.mark.pit
def test_narrative_provenance_includes_used_profile_but_not_other_topic(world, payload):
    ledger, clock, source, seed, engine, policy = world
    history = receive(world, "历史画像证据", locator="fixture:profile-history")
    unrelated = receive(world, "其他主题画像证据", locator="fixture:other-topic")
    clock.advance(hours=3)
    current = receive(world, "当前传播", locator="fixture:current")
    profiles = []
    for identity, topic, evidence in (("USED_PROFILE", seed.dna.domain_ids[0], history),
                                       ("OTHER_PROFILE", "OTHER_TOPIC", unrelated)):
        now = clock()
        data = {**payload["narrative_source_profiles"][0], "object_id": identity,
            "recorded_at": now, "available_at": now, "computed_at": now,
            "input_version_refs": [{**ref(source), "available_at": source.available_at},
                                   {**ref(evidence), "available_at": evidence.available_at}],
            "evidence_refs": [ref(evidence)], "source_ref": ref(source), "source_id": source.source_id,
            "topic_id": topic, "category": "EXPLAINER", "sample_n": 0,
            "observation_window": {"start": now-timedelta(minutes=5), "end": now},
            "leading_stats": None, "following_stats": None, "posthoc_stats": None,
            "edit_stats": None, "delete_stats": None, "lead_time_stats": None}
        profiles.append(engine.register_profile(NarrativeSourceProfile.model_validate(data)))
    state = evaluate(world, "profile-provenance", profile_refs=[vr(p) for p in profiles])
    dims = transitions(ledger, state)
    assert refs(dims["NARRATIVE"].evidence_refs) == refs([current, history])
    assert not dims["FACT"].evidence_refs and not dims["PRICING"].evidence_refs
    diffusion = ledger.history(as_of=clock(), kind="DiffusionSummary")[-1]
    assert refs(diffusion.profile_refs) == refs(profiles[:1])
