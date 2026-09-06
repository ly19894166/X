"""复用Phase2事务/发布回执；状态、时钟、lineage、触发器均追加固定版本。"""
from datetime import timedelta

from ..contracts import EventVersion, EvidenceVersion, Source, NarrativeSourceProfile
from ..contracts.common import DerivedEnvelope, PITQuery, TypeAdapter, UTCDateTime, VersionRef
from ..ledger.contracts import EvidenceChange, NoveltyDecision, OriginClusterVersion
from ..ledger.store import digest, ref
from .contracts import (Rules, StatePolicy, EvidenceAssessment, SecurityPriceObservation,
                        EventStateSnapshot, RecomputeTrigger, EventClock)
from .reducers import check_transition, fact_reduce, narrative_reduce, pricing_reduce

NARRATIVE_TO_LEGACY = {"QUIET": "SILENT", "PROFESSIONAL_DISCOVERY": "EXPERT_DISCOVERY", "DECAY": "DECAYING"}
PRICE_TO_LEGACY = {"LOCAL_REPRICING": "PARTIAL_REPRICING"}
STAMPS = {"object_id", "version", "recorded_at", "available_at", "computed_at", "content_hash",
          "run_id", "input_version_refs", "supersedes_version"}


def key_of(r):
    return r.object_id, r.version


def unique_refs(items):
    return [dict(object_id=k[0], version=k[1]) for k in sorted({key_of(r) for r in items})]


class StateEngine:
    def __init__(self, ledger):
        self.ledger = ledger

    def _input(self, view, reference, cls, cutoff):
        value = view.get(key_of(reference))
        if value is None or not isinstance(value, cls):
            raise ValueError("STATE_REFERENCE：输入类型或固定版本缺失")
        value.require_visible(PITQuery(as_of=cutoff, mode="LIVE_FORWARD"))
        return value

    @staticmethod
    def _event_evidence(view, event_id):
        return {key_of(r) for e in view.values() if isinstance(e, EventVersion) and e.event_id == event_id for r in e.evidence_refs}

    def _register(self, kind, identity, version, payload, inputs, policy_version="STATE_RULES_V0.1"):
        key = "STATE_INPUT:" + identity + ":" + str(version)
        payload = {**payload, "policy_version": policy_version}
        def build(conn, view, batch):
            for r in inputs:
                self._input(view, VersionRef(**r), DerivedEnvelope if kind == "StatePolicy" else object, self.ledger.now())
            self.ledger._put(conn, batch, kind, identity, version, payload, inputs)
        self.ledger._write(key, digest([kind, payload, inputs]), build)
        return self.ledger.get(identity, version)

    def policy(self, identity="STATE_POLICY", version=1, **settings):
        rules = Rules.model_validate(settings)
        return self._register("StatePolicy", identity, version, {"rules": rules.model_dump()}, [], f"{identity}:{version}")

    def register_profile(self, profile: NarrativeSourceProfile):
        if not isinstance(profile, NarrativeSourceProfile):
            raise ValueError("PROFILE_TYPE：仅登记叙事来源画像")
        profile.require_visible(PITQuery(as_of=self.ledger.now(), mode="LIVE_FORWARD"))
        payload = {k: v for k, v in profile.model_dump(mode="json").items() if k not in STAMPS}
        return self._register("NarrativeSourceProfile", profile.object_id, profile.version, payload,
                              unique_refs(profile.input_version_refs), profile.policy_version)

    def assess(self, event_ref, evidence_ref, *, assessment_key, kind, quoted_span, reviewed_by,
               interpretation_zh, authority_scope_zh=None, resolves_refs=(), event_started_at=None):
        cutoff = self.ledger.now()
        view = {key_of(r): r for r in self.ledger.history(as_of=cutoff)}
        event = self._input(view, event_ref, EventVersion, cutoff)
        evidence = self._input(view, evidence_ref, EvidenceVersion, cutoff)
        if key_of(evidence) not in self._event_evidence(view, event.event_id):
            raise ValueError("ASSESS_SCOPE：证据不属于本事件")
        source = self._input(view, evidence.source_ref, Source, cutoff)
        if evidence.quality_status != "VALIDATED" or quoted_span not in self.ledger.raw(evidence.raw_object_ref).decode("utf-8", errors="replace"):
            raise ValueError("ASSESS_PROOF：必须引用已校验原文的具体片段")
        if kind != "PLAUSIBLE" and evidence.claim_kind != "FACT":
            raise ValueError("FACT_KIND：声明/预测/传闻不自动变成主张事实")
        if kind in ("OFFICIAL_CONFIRMATION", "OFFICIAL_DENIAL") and not (
                source.identity_status == "VERIFIED" and source.tier == "S0" and "FACT" in source.roles
                and evidence.is_first_hand and authority_scope_zh):
            raise ValueError("OFFICIAL_PROOF：需负责机构已验证的一手事实文件与权限说明")
        if kind in ("IMPLEMENTATION", "INVALIDATION", "SUPPORT") and not (
                evidence.is_first_hand and source.identity_status == "VERIFIED"):
            raise ValueError("PRIMARY_PROOF：此主张需已验证一手材料")
        prior = [a for a in view.values() if isinstance(a, EvidenceAssessment) and a.event_ref.object_id == event.event_id]
        if kind == "IMPLEMENTATION" and any(a.evidence_ref == evidence_ref and a.kind == "OFFICIAL_CONFIRMATION" for a in prior):
            raise ValueError("IMPLEMENTATION_NEW：宣布材料不能重复充当新的实施证据")
        if kind == "IMPLEMENTATION" and any(view[key_of(a.evidence_ref)].available_at >= evidence.available_at
                                            for a in prior if a.kind == "OFFICIAL_CONFIRMATION"):
            raise ValueError("IMPLEMENTATION_NEW：实施证据必须晚于已使用的宣布证据")
        if kind == "RESOLUTION":
            if not resolves_refs:
                raise ValueError("RESOLUTION_PROOF：必须明确解除哪些反证版本")
            for r in resolves_refs:
                old = self._input(view, r, EvidenceAssessment, cutoff)
                if old.event_ref.object_id != event.event_id or old.kind not in ("COUNTEREVIDENCE", "OFFICIAL_DENIAL", "INVALIDATION"):
                    raise ValueError("RESOLUTION_SCOPE：只能解除本事件的具体反证")
                if evidence.available_at <= view[key_of(old.evidence_ref)].available_at:
                    raise ValueError("RESOLUTION_NEW：解除反证必须有后来新证据")
        inputs = unique_refs([event_ref, evidence_ref, evidence.source_ref, *resolves_refs])
        return self._register("EvidenceAssessment", "ASSESS:" + assessment_key, 1,
            dict(event_ref=ref(event), evidence_ref=ref(evidence), kind=kind, quoted_span=quoted_span,
                 reviewed_by=reviewed_by, interpretation_zh=interpretation_zh, authority_scope_zh=authority_scope_zh,
                 event_started_at=TypeAdapter(UTCDateTime).validate_python(event_started_at).isoformat() if event_started_at else None,
                 resolves_refs=unique_refs(resolves_refs), evidence_refs=[ref(evidence)]), inputs)

    def price(self, event_ref, *, observation_key, security_id, window, observation, evidence_refs=(),
              basis_zh, cross_asset_confirmed=False):
        cutoff = self.ledger.now()
        view = {key_of(r): r for r in self.ledger.history(as_of=cutoff)}
        event = self._input(view, event_ref, EventVersion, cutoff)
        for r in evidence_refs:
            evidence = self._input(view, r, EvidenceVersion, cutoff)
            if key_of(evidence) not in self._event_evidence(view, event.event_id):
                raise ValueError("PRICE_SCOPE：价格fixture证据必须关联本事件")
        return self._register("SecurityPriceObservation", "PRICE:" + observation_key, 1,
            dict(event_ref=ref(event), security_id=security_id, observation_window=window.model_dump(mode="json"),
                 observation=observation, basis_zh=basis_zh, evidence_refs=unique_refs(evidence_refs),
                 cross_asset_confirmed=cross_asset_confirmed), unique_refs([event_ref, *evidence_refs]))

    def evaluate(self, event_ref, policy_ref, *, request_key, as_of, assessment_refs=(), price_refs=(), profile_refs=()):
        cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
        if cutoff > self.ledger.now():
            raise ValueError("PIT_STATE：不能以未来时点运算")
        key = "STATE_RUN:" + request_key
        fingerprint = digest([ref(event_ref), ref(policy_ref), cutoff.isoformat(),
                              unique_refs(assessment_refs), unique_refs(price_refs), unique_refs(profile_refs)])
        result_id = "SNAP:" + key
        def build(conn, full_view, batch):
            view = {k: r for k, r in full_view.items() if r.available_at <= cutoff}
            event = self._input(view, event_ref, EventVersion, cutoff)
            latest = max((r.version for r in full_view.values() if isinstance(r, EventVersion) and r.event_id == event.event_id))
            if latest != event.version:
                raise ValueError("EXPECTED_VERSION：事件已有新版本，拒绝覆盖或倒写")
            policy = self._input(view, policy_ref, StatePolicy, cutoff)
            previous = max((r for r in view.values() if isinstance(r, EventStateSnapshot) and r.event_ref.object_id == event.event_id),
                           key=lambda r: r.available_at, default=None)
            past_refs = previous.assessment_refs if previous else ()
            assessments = [self._input(view, VersionRef(**r), EvidenceAssessment, cutoff)
                           for r in unique_refs([*past_refs, *assessment_refs])]
            prices = [self._input(view, r, SecurityPriceObservation, cutoff) for r in price_refs]
            profiles = [self._input(view, r, NarrativeSourceProfile, cutoff) for r in profile_refs]
            if any(a.event_ref.object_id != event.event_id for a in [*assessments, *prices]):
                raise ValueError("STATE_SCOPE：其他事件输入不得混入")
            event_evidence = self._event_evidence(view, event.event_id)
            evidence = [r for k, r in view.items() if k in event_evidence and isinstance(r, EvidenceVersion)]
            sources = [self._input(view, r.source_ref, Source, cutoff) for r in evidence]
            clusters = [r for r in view.values() if isinstance(r, OriginClusterVersion)
                        and set(r.member_origin_ids) & {e.origin_cluster_id for e in evidence}]
            resolved_refs = {key_of(r) for a in assessments if a.kind == "RESOLUTION" for r in a.resolves_refs}
            resolved_at = max((a.available_at for a in assessments if key_of(a) in resolved_refs), default=None)
            support = [a.evidence_ref for a in assessments if a.kind == "SUPPORT"
                       and (resolved_at is None or a.available_at > resolved_at)]
            summary = self.ledger.origin_summary(as_of=cutoff, event_id=event.event_id, evidence_refs=support)
            support_evidence = [view[key_of(r)] for r in support]
            support_origins = {e.origin_cluster_id for e in support_evidence}
            support_clusters = [c for c in clusters if set(c.member_origin_ids) & support_origins]
            input_refs = unique_refs([event, policy, *evidence, *sources, *clusters, *assessments, *prices, *profiles,
                                     *([previous] if previous else [])])
            def put(kind, identity, payload, extra=(), version=1):
                refs = { (r["object_id"], r["version"]): r for r in [*input_refs, *extra] }
                self.ledger._put(conn, batch, kind, identity, version,
                                 {**payload, "policy_version": policy.policy_version}, list(refs.values()))
                return dict(object_id=identity, version=version)
            origin_ref = put("OriginSourceSummary", "ORIGIN_SUM:" + batch,
                dict(event_ref=ref(event), as_of=cutoff.isoformat(), origin_count=summary["origin_count"],
                     independent_source_count=summary["independent_source_count"], independence_status=summary["status"],
                     cluster_refs=unique_refs(support_clusters), source_refs=unique_refs(e.source_ref for e in support_evidence),
                     evidence_refs=unique_refs(support)))
            window_start = cutoff - timedelta(seconds=policy.rules.window_seconds)
            previous_start = window_start - timedelta(seconds=policy.rules.window_seconds)
            current = [e for e in evidence if window_start < e.first_seen_at <= cutoff]
            previous_window = [e for e in evidence if previous_start < e.first_seen_at <= window_start]
            old_sources = {e.source_id for e in previous_window}
            ids = sorted({e.source_id for e in current})
            current_sources = [view[key_of(e.source_ref)] for e in current]
            tiers = sorted({s.tier for s in current_sources})
            used_profiles = [p for p in profiles if p.source_id in ids and p.topic_id in event.dna.domain_ids]
            professional = {p.source_id for p in used_profiles
                            if p.category in ("INDUSTRY_LEADER", "EXPLAINER") and p.sample_n > 0}
            changes = [r for r in view.values() if isinstance(r, EvidenceChange) and key_of(r.evidence_ref) in event_evidence
                       and window_start < r.observed_at <= cutoff]
            narrative_evidence = [*current, *previous_window,
                *(r.evidence_ref for r in changes if r.change_type in ("EDIT", "DELETE", "RETRACT")),
                *(r for p in used_profiles for r in p.evidence_refs)]
            input_refs.extend(unique_refs(narrative_evidence))
            diffusion = dict(event_ref=ref(event), observation_window=dict(start=window_start.isoformat(), end=cutoff.isoformat()),
                source_ids=ids, source_tiers=tiers,
                origin_count=self.ledger.origin_summary(as_of=cutoff, event_id=event.event_id, evidence_refs=current)["origin_count"],
                previous_source_count=len(old_sources), professional_sources=len(professional),
                edit_count=len({r.evidence_ref.object_id for r in changes if r.change_type == "EDIT"}),
                delete_count=len({r.evidence_ref.object_id for r in changes if r.change_type in ("DELETE", "RETRACT")}),
                profile_refs=unique_refs(used_profiles), source_refs=unique_refs(current_sources),
                evidence_refs=unique_refs(narrative_evidence))
            diffusion_ref = put("DiffusionSummary", "DIFFUSION:" + batch, diffusion)
            novel = [r for r in view.values() if isinstance(r, NoveltyDecision) and key_of(r.evidence_ref) in event_evidence
                     and r.classification in ("R3", "R4", "R5") and (previous is None or r.available_at > previous.available_at)]
            # UNDETERMINED为HOLD审计，不送入正式派生输入。只消费合格material决定。
            input_refs.extend(unique_refs(novel))
            old_fact = previous.fact_state if previous else event.fact_state
            old_narrative = previous.narrative_state if previous else {v:k for k,v in NARRATIVE_TO_LEGACY.items()}.get(event.narrative_state, event.narrative_state)
            old_price = previous.pricing_state if previous else {v:k for k,v in PRICE_TO_LEGACY.items()}.get(event.pricing_state, event.pricing_state)
            facts = fact_reduce(old_fact, assessments, summary["independent_source_count"])
            if any(r.classification == "R5" for r in novel) and facts[0] == old_fact:
                facts = old_fact, "反证_R5仅触发重算需显式主张核验", "HOLD"
            narrative = narrative_reduce(old_narrative, diffusion, policy.rules)
            # 每个security只允许一个指定观察版本，避免将新旧观察混成分歧。
            if len({p.security_id for p in prices}) != len(prices):
                raise ValueError("PRICE_DUPLICATE：同一证券只能提供一个观察版本")
            pricing = pricing_reduce(old_price, prices)
            pricing_evidence = [r for p in prices for r in p.evidence_refs]
            dimension_evidence = {"FACT": [a.evidence_ref for a in assessments],
                                  "NARRATIVE": narrative_evidence, "PRICING": pricing_evidence}
            price_summary = put("EventPriceSummary", "PRICE_SUM:" + batch,
                dict(event_ref=ref(event), pricing_state=pricing[0], observation_refs=unique_refs(prices), evidence_refs=unique_refs(pricing_evidence)))
            transition_refs = []
            for dimension, before, reduced in (("FACT", old_fact, facts), ("NARRATIVE", old_narrative, narrative), ("PRICING", old_price, pricing)):
                after, reason, outcome = reduced
                check_transition(dimension, before, after)
                transition_refs.append(put("StateTransition", dimension + ":" + batch,
                    dict(event_ref=ref(event), dimension=dimension, previous_state=before, new_state=after,
                         origin_source_summary_ref=origin_ref, policy_ref=ref(policy), outcome=outcome,
                         reason_codes=[reason], evidence_refs=unique_refs(dimension_evidence[dimension])), [origin_ref, diffusion_ref, price_summary]))
            reasons = {"R3": "R3_MATERIAL_EVIDENCE", "R4": "R4_EVENT_MUTATION", "R5": "R5_COUNTEREVIDENCE"}
            trigger_reasons = {reasons[r.classification] for r in novel}
            if any(e.version == 1 and e.is_first_hand and e.quality_status == "VALIDATED"
                   and view[key_of(e.source_ref)].identity_status == "VERIFIED"
                   and (previous is None or e.available_at > previous.available_at) for e in evidence):
                trigger_reasons.add("NEW_PRIMARY_EVIDENCE")
            if facts[0] == "CONTRADICTED" and old_fact not in ("CONTRADICTED", "INVALIDATED"):
                trigger_reasons.add("R5_COUNTEREVIDENCE")
            new_assessments = [a for a in assessments if previous is None or a.available_at > previous.available_at]
            for a in new_assessments:
                if a.kind in ("OFFICIAL_CONFIRMATION", "OFFICIAL_DENIAL"):
                    trigger_reasons.add(a.kind)
                elif a.kind in ("COUNTEREVIDENCE", "INVALIDATION"):
                    trigger_reasons.add("R5_COUNTEREVIDENCE")
                elif view[key_of(a.evidence_ref)].is_first_hand:
                    trigger_reasons.add("NEW_PRIMARY_EVIDENCE")
            accelerating = narrative[0] in ("RAPID_DIFFUSION", "MAINSTREAM", "CROWDED") and narrative[0] != old_narrative
            if accelerating:
                trigger_reasons.add("NARRATIVE_ACCELERATION")
            if pricing[0] != old_price:
                trigger_reasons.add("PRICE_STATE_CHANGE")
            if any(p.cross_asset_confirmed for p in prices):
                trigger_reasons.add("CROSS_ASSET_CONFIRMATION")
            priority = "P0" if trigger_reasons & {"R5_COUNTEREVIDENCE", "OFFICIAL_DENIAL"} else "P1" if trigger_reasons - {"NARRATIVE_ACCELERATION"} else "P2" if trigger_reasons else "P3"
            previous_clock = view.get(key_of(previous.clock_ref)) if previous else None
            starts = {a.event_started_at for a in assessments if a.event_started_at is not None}
            if previous_clock and previous_clock.event_started_at:
                starts.add(previous_clock.event_started_at)
            # 开始时间有分歧时保留未知；不得用发布时间或首次发现时间猜测。
            started = next(iter(starts)) if len(starts) == 1 else None
            clock_data = dict(event_ref=ref(event), observed_at=cutoff.isoformat(),
                event_started_at=started.isoformat() if started else None, first_seen_at=event.first_seen_at.isoformat(), last_material_update_at=event.last_material_update_at.isoformat(),
                event_age_seconds=(cutoff-started).total_seconds() if started else None, observed_age_seconds=(cutoff-event.first_seen_at).total_seconds(),
                time_since_last_material_update_seconds=(cutoff-event.last_material_update_at).total_seconds(), life_band=policy.rules.life_band)
            for name, updated in (
                    ("last_confirmation_at", max((a.available_at for a in new_assessments if a.kind in ("PARTIAL", "SUPPORT", "OFFICIAL_CONFIRMATION", "IMPLEMENTATION")), default=None)),
                    ("last_counterevidence_at", max([a.available_at for a in new_assessments if a.kind in ("COUNTEREVIDENCE", "OFFICIAL_DENIAL", "INVALIDATION")] + [r.available_at for r in novel if r.classification == "R5"], default=None)),
                    ("last_narrative_acceleration_at", cutoff if accelerating else None),
                    ("last_market_reaction_at", max((p.available_at for p in prices if p.observation not in ("UNKNOWN", "NO_REACTION")), default=None))):
                stamp = max(filter(None, (updated, getattr(previous_clock, name, None))), default=None)
                clock_data[name] = stamp.isoformat() if stamp else None
            clock_ref = put("EventClock", "CLOCK:" + batch, clock_data, [*transition_refs])
            event_payload = {k:v for k,v in event.model_dump(mode="json").items() if k not in STAMPS}
            event_payload.update(fact_state=facts[0], narrative_state=NARRATIVE_TO_LEGACY.get(narrative[0], narrative[0]),
                pricing_state=PRICE_TO_LEGACY.get(pricing[0], pricing[0]), priority=priority,
                supersedes_version=event.version, revision_reason="Phase3三维独立规则重算", evidence_refs=unique_refs(evidence))
            new_event_ref = put("EventVersion", event.object_id, event_payload, [*transition_refs, clock_ref], event.version+1)
            put("EventLedgerEntry", "LED:" + event.event_id,
                dict(event_ref=new_event_ref, previous_version=event.version, operation="APPEND", idempotency_key=batch), [new_event_ref], event.version+1)
            put("EventStateSnapshot", result_id, dict(event_ref=new_event_ref, fact_state=facts[0], narrative_state=narrative[0],
                pricing_state=pricing[0], clock_ref=clock_ref, transition_refs=transition_refs,
                assessment_refs=unique_refs(assessments), priority=priority, lifecycle_status=event.lifecycle_status),
                [new_event_ref, clock_ref, *transition_refs])
            if trigger_reasons:
                self._trigger(conn, view, batch, new_event_ref, sorted(trigger_reasons), priority, cutoff,
                              policy, input_refs + [new_event_ref])
            self.ledger.fault("after_state")
        self.ledger._write(key, fingerprint, build)
        return self.ledger.get(result_id, 1)

    def _trigger(self, conn, view, batch, event_ref, reasons, priority, cutoff, policy, inputs):
        ordinary = set(reasons) == {"NARRATIVE_ACCELERATION"}
        prior = max((r for r in view.values() if isinstance(r, RecomputeTrigger) and r.event_ref.object_id == event_ref["object_id"]
                     and r.dispatch == "READY" and r.trigger_reasons == ("NARRATIVE_ACCELERATION",)),
                    key=lambda r: r.available_at, default=None)
        coalesced = ordinary and prior is not None and cutoff < prior.available_at + timedelta(seconds=policy.rules.cooldown_seconds)
        parent = ref(prior) if coalesced else None
        not_before = prior.available_at + timedelta(seconds=policy.rules.cooldown_seconds) if coalesced else cutoff
        self.ledger._put(conn, batch, "RecomputeTrigger", "TRIGGER:" + batch + ":" + event_ref["object_id"], 1,
            dict(event_ref=event_ref, trigger_reasons=reasons, priority=priority,
                 idempotency_key="RECOMPUTE:"+batch+":"+event_ref["object_id"],
                 dispatch="COALESCED" if coalesced else "READY", not_before=not_before.isoformat(), cooldown_parent_ref=parent,
                 policy_version=policy.policy_version, reason_codes=["重算_传播归并" if coalesced else "重算_证据优先非看多评分"]),
            inputs + ([parent] if parent else []))

    def pending(self, *, as_of):
        """只给出版本化研究队列，不运行研究；合并传播挂靠既有任务，无无限重复任务。"""
        cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
        tasks = {}
        for trigger in self.ledger.history(as_of=cutoff, kind="RecomputeTrigger"):
            group = trigger.cooldown_parent_ref.object_id if trigger.cooldown_parent_ref else trigger.object_id
            tasks[group] = trigger
        return sorted((r for r in tasks.values() if r.not_before <= cutoff),
                      key=lambda r: (r.priority, r.available_at, r.object_id))

    def lineage(self, operation, parent_refs, policy_ref, *, request_key, interpretation_zh,
                evidence_refs=(), child_seeds=(), novelty_ref=None, mutated_seed=None):
        """显式人工事件身份裁定；所有父/子版本与关系同事务，不做自动语义合并。"""
        if operation not in ("MERGE", "SPLIT", "MUTATE", "ARCHIVE", "REACTIVATE"):
            raise ValueError("LINEAGE_ENUM：未知内部操作")
        if (len({r.object_id for r in parent_refs}) != len(parent_refs) or not parent_refs
                or (operation == "MERGE" and (len(parent_refs) < 2 or len(child_seeds) != 1))
                or (operation == "SPLIT" and (len(parent_refs) != 1 or len(child_seeds) < 2))
                or (operation in ("MUTATE", "ARCHIVE", "REACTIVATE") and (len(parent_refs) != 1 or child_seeds))):
            raise ValueError("LINEAGE_SHAPE：MERGE需多父一子、SPLIT需一父多子，其余为单事件新版本")
        if operation != "ARCHIVE" and not evidence_refs:
            raise ValueError("LINEAGE_PROOF：必须提供本次裁定的具体证据")
        if mutated_seed is not None and (operation != "MUTATE" or mutated_seed.event_id != parent_refs[0].object_id):
            raise ValueError("MUTATE_ID：性质变化保留同一事件ID")
        key = "LINEAGE_RUN:" + request_key
        fingerprint = digest([operation, unique_refs(parent_refs), ref(policy_ref), interpretation_zh,
                              unique_refs(evidence_refs), [s.model_dump(mode="json") for s in child_seeds],
                              ref(novelty_ref) if novelty_ref else None,
                              mutated_seed.model_dump(mode="json") if mutated_seed else None])
        def build(conn, view, batch):
            cutoff = self.ledger.now()
            policy = self._input(view, policy_ref, StatePolicy, cutoff)
            parents = [self._input(view, r, EventVersion, cutoff) for r in parent_refs]
            for parent in parents:
                if parent.version != max(r.version for r in view.values() if isinstance(r, EventVersion) and r.event_id == parent.event_id):
                    raise ValueError("EXPECTED_VERSION：Lineage父事件已变化")
            evidence = [self._input(view, r, EvidenceVersion, cutoff) for r in evidence_refs]
            novelty = self._input(view, novelty_ref, NoveltyDecision, cutoff) if novelty_ref else None
            if operation in ("MUTATE", "REACTIVATE"):
                if novelty is None or novelty.classification not in (("R4",) if operation == "MUTATE" else ("R3", "R4", "R5")):
                    raise ValueError("LINEAGE_MATERIAL：变性质需R4，复活需R3/R4/R5新材料")
                if key_of(novelty.evidence_ref) not in {key_of(e) for e in evidence}:
                    raise ValueError("LINEAGE_MATERIAL：material决定与材料版本不匹配")
                if key_of(novelty.evidence_ref) not in self._event_evidence(view, parents[0].event_id):
                    raise ValueError("LINEAGE_SCOPE：其他事件的material不可用")
            if operation == "REACTIVATE":
                archived = [r for r in view.values() if isinstance(r, EventVersion) and r.event_id == parents[0].event_id and r.revision_reason.startswith("Phase3 ARCHIVE")]
                if parents[0].lifecycle_status != "ARCHIVED" or not archived or novelty.available_at <= max(r.available_at for r in archived):
                    raise ValueError("REACTIVATE_NEW：归档后新的material证据才能复活")
            inputs = unique_refs([policy, *parents, *evidence, *([novelty] if novelty else [])])
            for parent in parents:
                inputs.extend(unique_refs(parent.evidence_refs))
                inputs.extend(unique_refs(parent.dna.actor_refs))
            outputs = []
            if child_seeds:
                if len({s.event_id for s in child_seeds}) != len(child_seeds) or any(s.event_id in {r.object_id for r in view.values()} for s in child_seeds):
                    raise ValueError("LINEAGE_ID：child必须使用新的不重复Event ID")
                for seed in child_seeds:
                    actor_refs = unique_refs(seed.dna.actor_refs)
                    for r in seed.dna.actor_refs:
                        self._input(view, r, object, cutoff)
                    payload = dict(event_id=seed.event_id, title_zh=seed.title_zh, dna=seed.dna.model_dump(mode="json"),
                        event_type="UNKNOWN", classification_missing_reason="人工Lineage尚未分类",
                        first_public_at=None, first_seen_at=cutoff.isoformat(), last_material_update_at=cutoff.isoformat(),
                        evidence_refs=unique_refs(evidence), revision_reason=f"Phase3 {operation}：{interpretation_zh}", policy_version=policy.policy_version)
                    self.ledger._put(conn, batch, "EventVersion", seed.event_id, 1, payload, inputs+actor_refs)
                    outputs.append(dict(object_id=seed.event_id, version=1))
            else:
                parent = parents[0]
                payload = {k:v for k,v in parent.model_dump(mode="json").items() if k not in STAMPS}
                if mutated_seed:
                    for r in mutated_seed.dna.actor_refs:
                        self._input(view, r, object, cutoff)
                    inputs.extend(unique_refs(mutated_seed.dna.actor_refs))
                    payload.update(title_zh=mutated_seed.title_zh, dna=mutated_seed.dna.model_dump(mode="json"))
                payload.update(supersedes_version=parent.version, revision_reason=f"Phase3 {operation}：{interpretation_zh}",
                               policy_version=policy.policy_version)
                if operation in ("ARCHIVE", "REACTIVATE"):
                    payload["lifecycle_status"] = "ARCHIVED" if operation == "ARCHIVE" else "ACTIVE"
                self.ledger._put(conn, batch, "EventVersion", parent.event_id, parent.version+1, payload, inputs)
                outputs.append(dict(object_id=parent.event_id, version=parent.version+1))
            lineage_ref = dict(object_id="LINEAGE:"+batch, version=1)
            self.ledger._put(conn, batch, "EventLineage", lineage_ref["object_id"], 1,
                dict(operation=operation, parent_refs=unique_refs(parents), child_refs=outputs,
                     idempotency_key=batch, interpretation_zh=interpretation_zh, evidence_refs=unique_refs(evidence),
                     policy_version=policy.policy_version), inputs+outputs)
            for out in outputs:
                self.ledger._put(conn, batch, "EventLedgerEntry", "LED:"+out["object_id"], out["version"],
                    dict(event_ref=out, previous_version=out["version"]-1 if out["version"]>1 else None,
                         operation="CREATE" if out["version"]==1 else "APPEND", idempotency_key=batch,
                         policy_version=policy.policy_version), inputs+[out,lineage_ref])
                reasons = ["LINEAGE_CHANGE"]
                if novelty and novelty.classification == "R5":
                    reasons.append("R5_COUNTEREVIDENCE")
                self._trigger(conn, view, batch, out, reasons,
                    "P0" if len(reasons)>1 else "P1", cutoff, policy, inputs+[out,lineage_ref])
            self.ledger.fault("after_lineage")
        self.ledger._write(key, fingerprint, build)
        return self.ledger.get("LINEAGE:"+key, 1)
