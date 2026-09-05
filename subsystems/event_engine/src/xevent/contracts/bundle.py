"""内存中的离线 fixture 校验；不是 Ledger、存储或事件发现器。"""
import hashlib
import json

from pydantic import Field, model_validator

from .common import Contract, Items, PITError, PITQuery, Text, VersionEnvelope
from .models import (
    Actor, ActorTopicProfile, EvidenceRelation, EvidenceVersion, EventVersion,
    NarrativeSourceProfile, Source, SourceTopicProfile, Statement,
)


def content_digest(record: VersionEnvelope) -> str:
    """内容摘要口径：规范化 UTC 后完整 JSON，排除自身 content_hash。"""
    value = record.model_dump(mode="json", exclude={"content_hash"})
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class OfflineFixture(Contract):
    fixture_version: Text = "X_EVENT_PHASE1_FIXTURE_V0.1"
    sources: Items[Source] = Field(min_length=1)
    source_topic_profiles: Items[SourceTopicProfile] = ()
    narrative_source_profiles: Items[NarrativeSourceProfile] = ()
    actors: Items[Actor] = ()
    actor_topic_profiles: Items[ActorTopicProfile] = ()
    statements: Items[Statement] = ()
    evidence_versions: Items[EvidenceVersion] = Field(min_length=1)
    evidence_relations: Items[EvidenceRelation] = ()
    event_versions: Items[EventVersion] = Field(min_length=1)
    raw_contents: dict[str, str] = Field(description="仅虚构 UTF-8 文本；键是 raw_object_ref")

    def records(self):
        for name in type(self).model_fields:
            if name not in ("fixture_version", "raw_contents"):
                yield from getattr(self, name)

    @model_validator(mode="after")
    def integrity(self):
        records = list(self.records())
        index = {(r.object_id, r.version): r for r in records}
        if len(index) != len(records):
            raise ValueError("DUPLICATE_VERSION：对象版本重复")
        dependencies = {}
        for record in records:
            key = (record.object_id, record.version)
            if content_digest(record) != record.content_hash:
                raise ValueError("CONTENT_HASH：规范化版本内容摘要不匹配")
            dependencies[key] = []
            declared = {(r.object_id, r.version) for r in record.input_version_refs}
            if len(declared) != len(record.input_version_refs):
                raise ValueError("DUPLICATE_INPUT：输入版本重复")
            for ref in record.input_version_refs:
                target_key = (ref.object_id, ref.version)
                target = index.get(target_key)
                if target is None:
                    raise ValueError("REFERENCE_MISSING：缺少具体输入版本，不能使用latest")
                if ref.available_at != target.available_at:
                    raise ValueError("PIT_REFERENCE_TIME：输入声明不能伪造真实版本可用时间")
                actual_public = target.public_pit.research_available_at if target.public_pit else None
                if ref.research_available_at != actual_public:
                    raise ValueError("PIT_REFERENCE_TIME：输入模拟时间与版本不一致")
                cutoff = (record.public_pit.research_available_at if record.public_pit else record.available_at)
                try:
                    # 现实有效区间与知识可用性分开；旧证据仍可引用。
                    target.require_visible(PITQuery(as_of=cutoff, mode=record.mode,
                                                    effective_at=target.effective_from))
                except PITError as exc:
                    raise ValueError(str(exc)) from exc
                dependencies[key].append(target_key)
            typed_refs = [(r, EvidenceVersion) for r in record.evidence_refs]
            for name, expected in (("source_ref", Source), ("actor_ref", Actor),
                                   ("organization_ref", Actor), ("evidence_ref", EvidenceVersion)):
                ref = getattr(record, name, None)
                if ref:
                    typed_refs.append((ref, expected))
            if isinstance(record, Actor):
                typed_refs.extend((ref, Source) for ref in record.verified_accounts)
            if isinstance(record, EventVersion):
                typed_refs.extend((ref, Actor) for ref in record.dna.actor_refs)
                if record.hypothesis_set_ref:
                    raise ValueError("PHASE_SCOPE：Phase 1 不解析尚未实现的假设集")
            if isinstance(record, EvidenceRelation):
                typed_refs.append((record.subject_ref, (Statement, EventVersion)))
            for ref, expected in typed_refs:
                ref_key = (ref.object_id, ref.version)
                if ref_key not in declared or not isinstance(index.get(ref_key), expected):
                    raise ValueError("REFERENCE_TYPE：关键引用缺少输入声明或对象类型错误")
            if isinstance(record, EvidenceVersion):
                raw = self.raw_contents.get(record.raw_object_ref)
                if raw is None or hashlib.sha256(raw.encode("utf-8")).hexdigest() != record.raw_content_hash:
                    raise ValueError("RAW_HASH：缺少原始 fixture 文本或摘要不匹配")
        # 等时输入也不能形成循环依赖；不执行事件图或去重业务。
        pending = dict(dependencies)
        while pending:
            ready = {key for key, refs in pending.items() if not any(ref in pending for ref in refs)}
            if not ready:
                raise ValueError("REFERENCE_CYCLE：输入版本引用形成循环")
            pending = {key: refs for key, refs in pending.items() if key not in ready}
        return self
