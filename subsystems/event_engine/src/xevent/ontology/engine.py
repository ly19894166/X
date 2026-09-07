"""Phase 4只追加本体/影响/候选对象；从不写EventVersion或三维状态。"""
from ..contracts import EventVersion, EvidenceVersion
from ..contracts.common import PITQuery, TypeAdapter, UTCDateTime, VersionRef
from ..ledger.store import digest, ref
from .contracts import (AliasResolution, ExternalCrosswalk, ImpactSpec, ImpactVariable, IndustryAlias,
    IndustryImpactRule, IndustrySegment, NarrativeTheme, ThemeIndustryRelation, OntologyDraft, OntologyVersion, phrase_key)
from .compatibility import POLICY, combine_impact_directions



def key(r):
    return r.object_id, r.version


def refs(items):
    return [dict(object_id=k[0], version=k[1]) for k in sorted({key(r) for r in items})]


class OntologyEngine:
    def __init__(self, ledger):
        self.ledger = ledger

    def _input(self, view, r, cls, cutoff):
        obj = view.get(key(r))
        if not isinstance(obj, cls):
            raise ValueError("ONTOLOGY_REFERENCE：固定版本缺失或类型错误，主题不能充当产业/影响")
        obj.require_visible(PITQuery(as_of=cutoff, mode="LIVE_FORWARD"))
        return obj

    @staticmethod
    def _next(view, identity, version, cls):
        previous = [r for r in view.values() if r.object_id == identity]
        if any(not isinstance(r, cls) for r in previous):
            raise ValueError("ONTOLOGY_ID_TYPE：稳定ID不得跨对象类型复用")
        old = max(previous, key=lambda r: r.version, default=None)
        if version != (old.version + 1 if old else 1):
            raise ValueError("ONTOLOGY_VERSION：只允许追加下一版本")
        return old

    def publish(self, draft: OntologyDraft):
        """发布完整不可变manifest；后续版本显式列出保留/修订项，不覆盖旧树。"""
        if not isinstance(draft, OntologyDraft):
            raise ValueError("ONTOLOGY_DRAFT：需要严格本体草稿契约")
        identity, version = draft.ontology_id, draft.version
        ontology_version = f"{identity}:{version}"
        def build(conn, view, batch):
            cutoff = self.ledger.now()
            old = self._next(view, identity, version, OntologyVersion)
            nodes = {s.industry_id: s for s in draft.segments}
            if old:
                for r in old.segment_refs:
                    previous = view[key(r)]
                    if previous.industry_id not in nodes or nodes[previous.industry_id].economic_role != previous.economic_role:
                        raise ValueError("INDUSTRY_STABLE_ID：旧ID须保留；不得重用ID改变经济角色，退役用effective_to")
            outputs = {"segment_refs": [], "alias_refs": [], "crosswalk_refs": [], "rule_refs": []}
            # 各对象使用自己的连续版本，manifest固定引用；新节点从v1起步。
            def planned(identity):
                versions = [r.version for r in view.values() if r.object_id == identity]
                return dict(object_id=identity, version=max(versions, default=0)+1)
            segment_refs = {s.industry_id: planned(s.industry_id) for s in draft.segments}
            def put(kind, out, payload, inputs):
                model = {"IndustrySegment": IndustrySegment, "IndustryAlias": IndustryAlias,
                         "ExternalCrosswalk": ExternalCrosswalk, "IndustryImpactRule": IndustryImpactRule}[kind]
                prior = self._next(view, out["object_id"], out["version"], model)
                self.ledger._put(conn, batch, kind, out["object_id"], out["version"],
                    {**payload, "ontology_version": ontology_version, "policy_version": POLICY,
                     "supersedes_version": prior.version if prior else None}, inputs + ([ref(prior)] if prior else []))
            for s in sorted(draft.segments, key=lambda s: s.industry_id):
                parent = segment_refs[s.parent_id] if s.parent_id else None
                put("IndustrySegment", segment_refs[s.industry_id],
                    {**s.model_dump(mode="json"), "parent_ref": parent,
                     "aliases": sorted({a.phrase for a in draft.aliases if a.industry_id == s.industry_id})}, [parent] if parent else [])
                outputs["segment_refs"].append(segment_refs[s.industry_id])
            for items, name, kind, bucket, target_name in (
                (draft.aliases, "alias_id", "IndustryAlias", "alias_refs", "industry_id"),
                (draft.crosswalks, "crosswalk_id", "ExternalCrosswalk", "crosswalk_refs", "x_industry_id"),
                (draft.rules, "rule_id", "IndustryImpactRule", "rule_refs", "industry_id")):
                for item in sorted(items, key=lambda r: getattr(r, name)):
                    out = planned(kind + ":" + getattr(item, name))
                    target = segment_refs.get(getattr(item, target_name))
                    for r in item.evidence_refs:
                        evidence = self._input(view, r, EvidenceVersion, cutoff)
                        if getattr(item, "mapping_status", None) == "VERIFIED" and (
                            evidence.quality_status != "VALIDATED" or evidence.claim_kind != "FACT"):
                            raise ValueError("MAPPING_PROOF：VERIFIED需已校验事实材料及显式核验记录")
                    previous = view.get((out["object_id"], out["version"]-1))
                    if isinstance(previous, IndustryAlias) and phrase_key(previous.phrase) != phrase_key(item.phrase):
                        raise ValueError("ALIAS_STABLE_ID：同alias_id不能更换原始短语")
                    if isinstance(previous, ExternalCrosswalk) and any(getattr(previous, n) != getattr(item, n)
                        for n in ("external_system", "provider_name", "external_code")):
                        raise ValueError("CROSSWALK_STABLE_ID：同ID不可换外部分类型号")
                    put(kind, out, {**item.model_dump(mode="json"), "industry_ref": target},
                        refs(item.evidence_refs) + ([target] if target else []))
                    outputs[bucket].append(out)
            inputs = [r for group in outputs.values() for r in group] + ([ref(old)] if old else [])
            self.ledger._put(conn, batch, "OntologyVersion", identity, version,
                dict(ontology_version=ontology_version, policy_version=POLICY, supersedes_version=old.version if old else None,
                     **outputs), inputs)
            self.ledger.fault("after_ontology")
        self.ledger._write(f"ONTOLOGY:{identity}:{version}", digest(draft.model_dump(mode="json")), build)
        return self.ledger.get(identity, version)

    def impact(self, impact_id, version, spec: ImpactSpec):
        if not isinstance(spec, ImpactSpec):
            raise ValueError("IMPACT_SPEC：需要严格影响契约")
        def build(conn, view, batch):
            cutoff = self.ledger.now()
            old = self._next(view, impact_id, version, ImpactVariable)
            event = self._input(view, spec.event_ref, EventVersion, cutoff)
            if old and old.event_ref.object_id != event.object_id:
                raise ValueError("IMPACT_EVENT：同Impact ID不得换事件")
            # 使用指定事件版本的证据，不借later EventVersion补足旧引用。
            event_evidence = {key(r) for r in event.evidence_refs}
            for r in spec.evidence_refs:
                ev = self._input(view, r, EvidenceVersion, cutoff)
                if key(ev) not in event_evidence:
                    raise ValueError("IMPACT_SCOPE：证据不属于指定事件版本")
            for r in spec.premise_refs:
                premise = self._input(view, r, (EvidenceVersion, ImpactVariable), cutoff)
                if ((isinstance(premise, EvidenceVersion) and key(premise) not in event_evidence) or
                    (isinstance(premise, ImpactVariable) and premise.event_ref.object_id != event.object_id)):
                    raise ValueError("IMPACT_SCOPE：推断前提跨事件")
            if spec.observation_kind == "OBSERVED":
                basis = spec.observation_basis
                evidence = self._input(view, basis.evidence_ref, EvidenceVersion, cutoff)
                if evidence.quality_status != "VALIDATED" or evidence.claim_kind != "FACT":
                    raise ValueError("OBSERVED_FACT：推断/传闻/意图不能冒充已观察事实；宣布与实施需分清")
                if basis.quoted_span not in self.ledger.raw(evidence.raw_object_ref).decode("utf-8", errors="replace"):
                    raise ValueError("OBSERVED_QUOTE：核验引用不在原文中")
            inputs = refs([spec.event_ref, *spec.evidence_refs, *spec.premise_refs, *([old] if old else [])])
            self.ledger._put(conn, batch, "ImpactVariable", impact_id, version,
                {**spec.model_dump(mode="json"), "impact_id": impact_id, "policy_version": POLICY,
                 "supersedes_version": old.version if old else None}, inputs)
        self.ledger._write(f"IMPACT:{impact_id}:{version}", digest(spec.model_dump(mode="json")), build)
        return self.ledger.get(impact_id, version)

    def theme(self, theme_id, version, *, event_ref, canonical_name_zh, description_zh, evidence_refs):
        payload = dict(theme_id=theme_id, event_ref=ref(event_ref), canonical_name_zh=canonical_name_zh,
                       description_zh=description_zh, evidence_refs=refs(evidence_refs), policy_version=POLICY)
        def build(conn, view, batch):
            cutoff = self.ledger.now()
            old = self._next(view, theme_id, version, NarrativeTheme)
            event = self._input(view, event_ref, EventVersion, cutoff)
            if not evidence_refs or old and old.event_ref.object_id != event.object_id:
                raise ValueError("THEME_SCOPE：主题需要本事件证据且不能更换事件")
            for r in evidence_refs:
                self._input(view, r, EvidenceVersion, cutoff)
                if key(r) not in {key(e) for e in event.evidence_refs}:
                    raise ValueError("THEME_SCOPE：主题证据不属于指定事件版本")
            self.ledger._put(conn, batch, "NarrativeTheme", theme_id, version,
                {**payload, "supersedes_version": old.version if old else None}, refs([event_ref, *evidence_refs, *([old] if old else [])]))
        self.ledger._write(f"THEME:{theme_id}:{version}", digest(payload), build)
        return self.ledger.get(theme_id, version)

    def resolve_alias(self, phrase, *, as_of, ontology_ref=None):
        cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
        view = {key(r): r for r in self.ledger.history(as_of=cutoff)}
        if ontology_ref:
            ontology = self._input(view, ontology_ref, OntologyVersion, cutoff)
        else:
            ontology = max((r for r in view.values() if isinstance(r, OntologyVersion)), key=lambda r:r.version, default=None)
        matches, aliases = {}, []
        if ontology:
            for r in ontology.segment_refs:
                s = view[key(r)]
                if phrase_key(s.canonical_name_zh) == phrase_key(phrase) and s.is_visible(PITQuery(as_of=cutoff, mode="LIVE_FORWARD")):
                    matches[key(s)] = s
            for r in ontology.alias_refs:
                a = self._input(view, r, IndustryAlias, cutoff)
                s = view[key(a.industry_ref)]
                if phrase_key(a.phrase) == phrase_key(phrase) and s.is_visible(PITQuery(as_of=cutoff, mode="LIVE_FORWARD")):
                    matches[key(s)] = s
                    aliases.append(a)
        matched = next(iter(matches.values())) if len(matches) == 1 else None
        return AliasResolution(phrase=phrase, as_of=cutoff, ontology_ref=ref(ontology) if ontology else None,
            industry_ref=ref(matched) if matched else None, alias_refs=refs(aliases),
            mapping_status="MATCHED" if matched else "UNRESOLVED", reason_zh="精确别名解析" if matched else "未知或歧义产业；不作模糊猜测")

    def theme_relation(self, relation_id, version, *, theme_ref, ontology_ref, industry_ref,
                       evidence_refs, mechanism_zh):
        payload = dict(theme_ref=ref(theme_ref), ontology_ref=ref(ontology_ref),
            industry_ref=ref(industry_ref) if industry_ref else None, evidence_refs=refs(evidence_refs),
            relation_status="ASSOCIATED" if industry_ref else "UNRESOLVED", mechanism_zh=mechanism_zh, policy_version=POLICY)
        def build(conn, view, batch):
            cutoff = self.ledger.now()
            old = self._next(view, relation_id, version, ThemeIndustryRelation)
            theme = self._input(view, theme_ref, NarrativeTheme, cutoff)
            ontology = self._input(view, ontology_ref, OntologyVersion, cutoff)
            if old and old.theme_ref != theme_ref:
                raise ValueError("THEME_RELATION_ID：同关系ID不得更换主题固定版本")
            if industry_ref:
                self._input(view, industry_ref, IndustrySegment, cutoff)
                if industry_ref not in ontology.segment_refs:
                    raise ValueError("THEME_ONTOLOGY：目标不属于指定本体版本")
            event = self._input(view, theme.event_ref, EventVersion, cutoff)
            for r in evidence_refs:
                self._input(view, r, EvidenceVersion, cutoff)
                if r not in event.evidence_refs:
                    raise ValueError("THEME_SCOPE：关联证据不属于主题的固定事件版本")
            inputs = refs([theme, ontology, *evidence_refs, *([industry_ref] if industry_ref else []), *([old] if old else [])])
            self.ledger._put(conn, batch, "ThemeIndustryRelation", relation_id, version,
                {**payload, "supersedes_version":old.version if old else None}, inputs)
        self.ledger._write(f"THEME_RELATION:{relation_id}:{version}", digest(payload), build)
        return self.ledger.get(relation_id, version)

    def crosswalk(self, crosswalk_id, ontology_ref, *, as_of):
        cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
        view = {key(r):r for r in self.ledger.history(as_of=cutoff)}
        ontology = self._input(view, ontology_ref, OntologyVersion, cutoff)
        values = [self._input(view, r, ExternalCrosswalk, cutoff) for r in ontology.crosswalk_refs]
        value = next((v for v in values if v.crosswalk_id == crosswalk_id), None)
        if value and value.industry_ref:
            self._input(view, value.industry_ref, IndustrySegment, cutoff)
        return value

    def resolve(self, impact_ref, ontology_ref, *, as_of, request_key):
        cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
        if cutoff > self.ledger.now():
            raise ValueError("PIT_ONTOLOGY：不能以未来知识时点计算")
        identity = "INDUSTRY_RESOLUTION:" + request_key
        def build(conn, full_view, batch):
            view = {k:r for k,r in full_view.items() if r.available_at <= cutoff}
            impact = self._input(view, impact_ref, ImpactVariable, cutoff)
            ontology = self._input(view, ontology_ref, OntologyVersion, cutoff)
            premise_evidence = {}
            premise_hold = []
            def has_economic_premise(value):
                if isinstance(value, EvidenceVersion):
                    premise_evidence[key(value)] = value
                    return value.claim_kind != "NARRATIVE"
                for r in value.evidence_refs:
                    premise_evidence[key(r)] = view[key(r)]
                premise_hold.append(value.validation_status == "HOLD")
                if value.observation_kind == "OBSERVED":
                    return True
                return any([has_economic_premise(view[key(r)]) for r in value.premise_refs])
            economic_premise = has_economic_premise(impact)
            candidates = []
            for r in ontology.rule_refs:
                rule = self._input(view, r, IndustryImpactRule, cutoff)
                if ((rule.variable_type, rule.target_object, rule.direction) !=
                    (impact.variable_type, impact.target_object, impact.direction)
                    or rule.fx_pair != impact.fx_pair
                    or not economic_premise or impact.direction == "UNKNOWN" or impact.geography == "UNKNOWN"
                    or rule.geography not in ("GLOBAL", impact.geography)):
                    continue
                industry = view[key(rule.industry_ref)]
                if not industry.is_visible(PITQuery(as_of=cutoff, mode="LIVE_FORWARD")):
                    continue
                candidates.append((rule, industry))
            outputs = []
            for rule, industry in candidates or [(None, None)]:
                out = dict(object_id="IND_CAND:" + digest([identity, rule.object_id if rule else None]), version=1)
                evidence = refs([*premise_evidence.values(), *(rule.evidence_refs if rule else [])])
                inputs = refs([impact, ontology, *([rule, industry] if rule else [])]) + evidence
                mapping_status = "UNRESOLVED" if rule is None else "HOLD" if (
                    any(premise_hold) or rule.mapping_status == "HOLD") else "CANDIDATE"
                self.ledger._put(conn, batch, "IndustryImpactCandidate", out["object_id"], 1,
                    dict(impact_ref=ref(impact), ontology_ref=ref(ontology), ontology_version=ontology.ontology_version,
                        industry_ref=ref(industry) if industry else None, rule_ref=ref(rule) if rule else None,
                        impact_direction=rule.impact_direction if rule else "UNKNOWN", path_role=rule.path_role if rule else "UNRESOLVED",
                        mapping_status=mapping_status, mechanism_zh=rule.mechanism_zh if rule else "无对应的可知规则；保留未解析经济路径",
                        uncertainty_zh=impact.uncertainty_zh or "确定性规则仅给出经济影响候选，尚未验证实际效果",
                        evidence_refs=evidence, policy_version=POLICY), inputs)
                outputs.append(out)
            targets = {}
            for rule, industry in candidates or [(None, None)]:
                targets.setdefault(key(industry) if industry else None, []).append(rule.impact_direction if rule else "UNKNOWN")
            directions = [dict(industry_ref=dict(object_id=k[0], version=k[1]) if k else None,
                               impact_direction=combine_impact_directions(values)) for k, values in sorted(targets.items(), key=lambda item:str(item[0]))]
            self.ledger._put(conn, batch, "IndustryResolution", identity, 1,
                dict(impact_ref=ref(impact), ontology_ref=ref(ontology), as_of=cutoff.isoformat(),
                     candidate_refs=outputs, industry_directions=directions, policy_version=POLICY), [ref(impact), ref(ontology), *outputs])
            self.ledger.fault("after_industry_resolution")
        self.ledger._write(identity, digest([ref(impact_ref), ref(ontology_ref), cutoff.isoformat(), POLICY]), build)
        return self.ledger.get(identity, 1)
