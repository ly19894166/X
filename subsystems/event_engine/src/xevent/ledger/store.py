"""单库不可变历史：业务事务与提交后回执分开，不伪造提交完成时间。"""
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import NullPool

from ..contracts import SCHEMAS, EvidenceVersion, EventVersion, Source
from ..contracts.bundle import content_digest
from ..contracts.common import DerivedEnvelope, InputVersionRef, PITQuery, UTCDateTime, VersionRef
from pydantic import TypeAdapter
from ..discovery.novelty import POLICY_VERSION, classify
from . import contracts as c
from .schema import batches, metadata, migrate, publications, raw_archive, receipts, records

MODELS = {**SCHEMAS, **{name: getattr(c, name) for name in (
    "EventLedgerEntry", "EvidenceChange", "OriginClusterVersion", "NoveltyDecision",
    "CollectorCursor", "OutboxJob", "SourceHealth")}}


def utcnow():
    return datetime.now(timezone.utc)


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def normalized(raw):
    return " ".join(raw.decode("utf-8", errors="replace").split()).encode("utf-8")


def ref(record):
    return dict(object_id=record.object_id, version=record.version)


class Ledger:
    def __init__(self, path, *, clock=utcnow, fault=lambda stage: None, recover_on_open=True):
        self.path = Path(path).resolve()
        self.clock, self.fault = clock, fault
        self.lock = threading.RLock()
        self._validated = {}
        self.engine = create_engine("sqlite:///" + self.path.as_posix(), poolclass=NullPool,
                                    connect_args={"timeout": 5})

        @event.listens_for(self.engine, "connect")
        def pragmas(db, _):
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=5000")

        if recover_on_open:
            migrate(self.engine)
            self.recover()
        elif not self.path.is_file():
            raise ValueError("DB_MISSING")
        else:
            with self.engine.connect() as conn:
                if conn.exec_driver_sql("PRAGMA user_version").scalar_one() != 1:
                    raise ValueError("MIGRATION_HOLD：只读Replay需要既有版本1数据库")

    def now(self):
        return TypeAdapter(UTCDateTime).validate_python(self.clock())

    def close(self):
        self.engine.dispose()

    def _view(self, conn, provisional=None):
        receipt_map = {r["batch_id"]: dict(r) for r in conn.execute(
            select(receipts, publications.c.available_at).join(publications, receipts.c.batch_id == publications.c.batch_id)).mappings()}
        if provisional:
            receipt_map.update(provisional)
        rows = [dict(r) for r in conn.execute(select(records)).mappings() if r["batch_id"] in receipt_map and r["kind"] != "RawObservation"]
        for row in conn.execute(select(records).where(records.c.kind == "RawObservation")).mappings():
            if digest(json.loads(row["payload"])) != row["payload_hash"]:
                raise ValueError("CONTENT_HASH：原始观察元数据被篡改")
        raw_rows = {r["raw_id"]: r for r in conn.execute(select(raw_archive)).mappings()}
        for raw in raw_rows.values():
            if digest(raw["raw_bytes"]) != raw["raw_hash"] or digest(normalized(raw["raw_bytes"])) != raw["normalized_hash"]:
                raise ValueError("RAW_HASH：原始证据被篡改，停止发布")
        index = {(r["object_id"], r["version"]): r for r in rows}
        result, visiting = {}, set()

        def load(key):
            if key in result:
                return result[key]
            if key in visiting or key not in index:
                raise ValueError("REFERENCE_INVALID：版本引用缺失或循环")
            visiting.add(key)
            row = index[key]
            payload = json.loads(row["payload"])
            if digest(payload) != row["payload_hash"]:
                raise ValueError("CONTENT_HASH：版本描述被篡改")
            inputs = [load((r["object_id"], r["version"])) for r in payload.pop("_inputs", [])]
            stamp = receipt_map[row["batch_id"]]
            available = TypeAdapter(UTCDateTime).validate_python(stamp["available_at"])
            if any(r.available_at > available for r in inputs):
                raise ValueError("PIT_INPUT：提交前输入尚不可用")
            if any(r.mode != "LIVE_FORWARD" or r.status in ("HOLD", "QUARANTINED") for r in inputs):
                raise ValueError("PIT_INPUT：输入模式或隔离状态非法")
            common = dict(object_id=key[0], version=key[1], recorded_at=stamp["recorded_at"],
                          available_at=stamp["available_at"], content_hash="0" * 64,
                          run_id=row["batch_id"], policy_version=POLICY_VERSION,
                          input_version_refs=[InputVersionRef(**ref(r), available_at=r.available_at) for r in inputs])
            model = MODELS[row["kind"]]
            if issubclass(model, DerivedEnvelope):
                common["computed_at"] = stamp["available_at"]
            cache_key = (row["payload_hash"], stamp["recorded_at"], stamp["available_at"],
                         tuple((r.object_id, r.version, r.content_hash) for r in inputs))
            cached = self._validated.get(key)
            if cached and cached[0] == cache_key:
                obj = cached[1]
            else:
                obj = model.model_validate({**payload, **common})
                obj = model.model_validate({**obj.model_dump(), "content_hash": content_digest(obj)})
                self._validated[key] = (cache_key, obj)
            if isinstance(obj, EvidenceVersion):
                raw = raw_rows.get(obj.raw_object_ref)
                if raw is None or raw["raw_hash"] != obj.raw_content_hash:
                    raise ValueError("RAW_MISSING：正式Evidence缺少原始内容或摘要不匹配")
            result[key] = obj
            visiting.remove(key)
            return obj

        for key in index:
            load(key)
        return result

    def _attest(self, batch_id, recorded_at, recovered):
        # recorded_at是业务事务COMMIT成功返回后的观测上界，绝非INSERT时间。
        # 回执属于发布目录，非第二次改写业务版本；崩溃缺回执时保守采用恢复时间。
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            if conn.execute(select(publications).where(publications.c.batch_id == batch_id)).first():
                conn.rollback()
                return
            prior_receipt = conn.execute(select(receipts).where(receipts.c.batch_id == batch_id)).mappings().first()
            if prior_receipt:
                recorded_at = TypeAdapter(UTCDateTime).validate_python(prior_receipt["recorded_at"])
            timestamp = self.now()
            marker = dict(batch_id=batch_id, recorded_at=recorded_at.isoformat(),
                          available_at=max(recorded_at, timestamp).isoformat(), recovered=int(recovered))
            self._view(conn, {batch_id: marker})
            # 必需的提交后校验真正完成后再取可用时间。
            marker["available_at"] = max(recorded_at, self.now()).isoformat()
            if not prior_receipt:
                conn.execute(receipts.insert().values(batch_id=batch_id, recorded_at=marker["recorded_at"],
                             contract_checked_at=marker["available_at"], recovered=int(recovered)))
                self.fault("before_receipt_commit")
            conn.commit()
            receipt_completed = max(recorded_at, self.now())
            self.fault("after_receipt_commit")
        # 可用时间另取于提交回执本身已耐久化之后，不能把回执写入前的时间用于PIT。
        # fence只存这一完成后观测，不覆盖已提交业务描述或回执；缺fence保持不可见。
        with self.engine.begin() as conn:
            if not conn.execute(select(publications).where(publications.c.batch_id == batch_id)).first():
                conn.execute(publications.insert().values(batch_id=batch_id, available_at=receipt_completed.isoformat(), recovered=int(recovered)))

    def recover(self):
        with self.lock, self.engine.connect() as conn:
            pending = conn.execute(select(batches.c.batch_id).where(
                ~batches.c.batch_id.in_(select(publications.c.batch_id)))).scalars().all()
        for batch_id in pending:
            self._attest(batch_id, self.now(), True)
        return len(pending)

    def _write(self, key, fingerprint, build):
        with self.lock:
            self.recover()
            with self.engine.connect() as conn:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                prior = conn.execute(select(batches).where(batches.c.batch_id == key)).mappings().first()
                if prior:
                    if prior["fingerprint"] != fingerprint:
                        raise ValueError("IDEMPOTENCY_CONFLICT：同一键对应不同内容")
                    conn.rollback()
                    return False
                view = self._view(conn)
                latest = max((r.available_at for r in view.values()), default=self.now())
                if self.now() < latest:
                    raise ValueError("CLOCK_ROLLBACK：系统时钟倒退，停止新发布")
                conn.execute(batches.insert().values(batch_id=key, fingerprint=fingerprint))
                build(conn, view, key)
                provisional = self.now().isoformat()
                self._view(conn, {key: dict(recorded_at=provisional, available_at=provisional)})
                self.fault("before_commit")
                conn.commit()
                committed = self.now()
                self.fault("after_commit")
            self._attest(key, committed, False)
            return True

    def _put(self, conn, batch, kind, object_id, version, payload, inputs=()):
        value = {**payload, "_inputs": list(inputs)}
        conn.execute(records.insert().values(object_id=object_id, version=version, kind=kind,
                     batch_id=batch, payload=json.dumps(value, ensure_ascii=False, sort_keys=True),
                     payload_hash=digest(value)))

    def register_source(self, source: Source):
        if source.mode != "LIVE_FORWARD":
            raise ValueError("PIT_MODE：Phase2不把PUBLIC档案登记成Live来源")
        if source.available_at > self.now():
            raise ValueError("PIT_SOURCE：不能提前登记未来才可知的来源版本")
        payload = source.model_dump(mode="json")
        for name in ("object_id", "version", "recorded_at", "available_at", "content_hash", "run_id",
                     "policy_version", "input_version_refs"):
            payload.pop(name, None)
        inputs = [ref(r) for r in source.input_version_refs]
        self._write("SOURCE:" + source.object_id + ":" + str(source.version), digest(payload),
                    lambda conn, view, key: self._put(conn, key, "Source", source.object_id, source.version, payload, inputs))
        return self.get(source.object_id, source.version)

    def history(self, *, as_of, kind=None):
        cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
        with self.lock, self.engine.connect() as conn:
            view = self._view(conn)
        return sorted((r for r in view.values() if r.available_at <= cutoff and
                       (kind is None or type(r).__name__ == kind)),
                      key=lambda r: (r.available_at, r.object_id, r.version))

    def get(self, object_id, version):
        with self.engine.connect() as conn:
            obj = self._view(conn).get((object_id, version))
        if obj is None:
            raise ValueError("REFERENCE_MISSING：找不到已发布的固定版本")
        return obj

    def replay(self, as_of):
        return [r.model_dump(mode="json") for r in self.history(as_of=as_of)]

    def raw(self, raw_id):
        with self.engine.connect() as conn:
            self._view(conn)  # 校验摘要
            row = conn.execute(select(raw_archive).join(publications, raw_archive.c.batch_id == publications.c.batch_id)
                               .where(raw_archive.c.raw_id == raw_id)).mappings().first()
        if row is None:
            raise ValueError("RAW_NOT_COMMITTED：不存在已发布的原始记录")
        return bytes(row["raw_bytes"])

    def ingest(self, observation: c.RawObservation, seed: c.EventSeed):
        # 一个来源的稳定内容版本定位构成幂等键；重试不能改变原始接收时间。
        logical = [observation.source_ref.object_id, observation.locator, observation.content_version]
        key = "INGEST:" + digest(logical)
        fingerprint = digest([observation.model_dump(mode="json", exclude={"raw", "first_seen_at", "collected_at"}),
                              digest(observation.raw), seed.model_dump(mode="json")])
        evidence_id = "EVD:" + digest(logical[:2])

        def build(conn, view, batch):
            source = view.get((observation.source_ref.object_id, observation.source_ref.version))
            if not isinstance(source, Source):
                raise ValueError("SOURCE_MISSING：先登记具体来源版本")
            if observation.collected_at > self.now():
                raise ValueError("PIT_RECEIVED：接收时间不能来自未来")
            previous = sorted((r for r in view.values() if r.object_id == evidence_id), key=lambda r: r.version)
            prior = previous[-1] if previous else None
            if prior is None and observation.change_type in ("EDIT", "DELETE", "RETRACT"):
                raise ValueError("PRIOR_MISSING：编辑/删除必须有原始版本")
            if prior and observation.change_type == "INITIAL":
                raise ValueError("CHANGE_REQUIRED：同一内容后续版本必须明确EDIT/DELETE/RETRACT")
            version = prior.version + 1 if prior else 1
            raw_id = "RAW:" + digest(logical)
            conn.execute(raw_archive.insert().values(raw_id=raw_id, batch_id=batch, source_id=source.source_id,
                         locator=observation.locator, content_version=observation.content_version,
                         first_seen_at=observation.first_seen_at.isoformat(), collected_at=observation.collected_at.isoformat(),
                         raw_bytes=observation.raw, raw_hash=digest(observation.raw), normalized_hash=digest(normalized(observation.raw))))
            self.fault("after_raw")
            evidence_inputs = [ref(source)]
            origin = None
            if observation.origin_ref:
                root = view.get((observation.origin_ref.object_id, observation.origin_ref.version))
                if not isinstance(root, EvidenceVersion):
                    raise ValueError("ORIGIN_REFERENCE：转载链必须引用已保存证据版本")
                origin, basis = root.origin_cluster_id, "EXPLICIT_CHAIN"
                evidence_inputs.append(ref(root))
            else:
                # 字节相同只在明确事件作用域内合源；不跨事件以通用文本误合并。
                event_evidence = {evref.object_id for evobj in view.values() if isinstance(evobj, EventVersion) and evobj.event_id == seed.event_id
                                  for evref in evobj.evidence_refs}
                match = next((r for r in view.values() if isinstance(r, EvidenceVersion) and r.object_id in event_evidence
                              and r.raw_content_hash == digest(observation.raw)), None)
                if prior:
                    origin, basis = prior.origin_cluster_id, "EXPLICIT_CHAIN"
                elif match:
                    origin, basis = match.origin_cluster_id, "EXACT_BYTES"
                    evidence_inputs.append(ref(match))
                else:
                    origin = "ORG:" + digest([seed.event_id, *logical[:2]])
                    basis = "FIRST_HAND" if observation.is_first_hand and source.identity_status == "VERIFIED" else "UNRESOLVED"
            origin_history = [r for r in view.values() if r.object_id == origin]
            known = basis == "FIRST_HAND" or any(r.verification == "KNOWN_ORIGIN" for r in origin_history)
            origin_version = max((r.version for r in origin_history), default=0) + 1
            e_ref = dict(object_id=evidence_id, version=version)
            ready = self.now()
            if prior:
                evidence_inputs.append(ref(prior))
            evidence = dict(evidence_id=evidence_id, source_id=source.source_id, source_ref=ref(source),
                            canonical_url_or_locator=observation.locator, original_language="und", raw_object_ref=raw_id,
                            raw_content_hash=digest(observation.raw), first_seen_text_ref=raw_id, origin_cluster_id=origin,
                            is_first_hand=observation.is_first_hand, independence_status="SAME_ORIGIN" if known else "UNKNOWN",
                            claim_kind=observation.claim_kind, published_at=observation.published_at, public_available_at=None,
                            first_seen_at=observation.first_seen_at, collected_at=observation.collected_at, ready_at=ready,
                            evidence_type="UNKNOWN", classification_missing_reason="Adapter不推断证据种类",
                            quality_status="VALIDATED", supersedes_version=prior.version if prior else None)
            # 描述字符串JSON化；规范化时间，不把ready误认为事实确认。
            evidence = json.loads(json.dumps(evidence, default=lambda v: v.isoformat()))
            self._put(conn, batch, "EvidenceVersion", evidence_id, version, evidence, evidence_inputs)
            self.fault("after_evidence")
            self._put(conn, batch, "EvidenceChange", "CHG:" + digest(logical), 1,
                      dict(evidence_ref=e_ref, prior_version_ref=ref(prior) if prior else None,
                           change_type=observation.change_type, observed_at=observation.first_seen_at.isoformat()), [e_ref])
            self._put(conn, batch, "OriginClusterVersion", origin, origin_version,
                      dict(member_origin_ids=[origin], basis=basis, verification="KNOWN_ORIGIN" if known else "HOLD",
                           evidence_refs=[e_ref]), [e_ref])
            previous_observation = None
            if prior:
                prior_row = conn.execute(select(records.c.payload).where(records.c.object_id == "OBS:" + prior.raw_object_ref)).scalar_one()
                previous_observation = self._decode_observation(json.loads(prior_row))
            level, reasons = classify(observation, previous_observation, diffusion=bool(origin_history and not prior))
            # 原始观察元数据作为独立描述保存在raw关联附表内容中，不作为研究输入。
            obs = observation.model_dump(mode="json", exclude={"raw"})
            obs["raw_hex"] = observation.raw.hex()
            # observation保存在批次内的专用版本，不走Phase1研究信封。
            conn.execute(records.insert().values(object_id="OBS:" + raw_id, version=1, kind="RawObservation",
                         batch_id=batch, payload=json.dumps(obs, ensure_ascii=False, sort_keys=True), payload_hash=digest(obs)))
            self._put(conn, batch, "NoveltyDecision", "NOV:" + digest(logical), 1,
                      dict(classification=level, evidence_ref=e_ref, evidence_refs=[e_ref], reason_codes=reasons,
                           status="HOLD" if level == "UNDETERMINED" else "READY"), [e_ref])
            events = [r for r in view.values() if isinstance(r, EventVersion) and r.event_id == seed.event_id]
            previous_event = max(events, key=lambda r: r.version) if events else None
            ev = previous_event.version + 1 if previous_event else 1
            event_ref = dict(object_id=seed.event_id, version=ev)
            event_inputs = [e_ref, *[r.model_dump() for r in seed.dna.actor_refs]]
            if previous_event:
                event_inputs.append(ref(previous_event))
            material_at = (ready if previous_event is None or level in ("R3", "R4", "R5")
                           else previous_event.last_material_update_at)
            self._put(conn, batch, "EventVersion", seed.event_id, ev,
                      dict(event_id=seed.event_id, title_zh=seed.title_zh, event_type="UNKNOWN", classification_missing_reason="Phase2不做事件分类",
                           dna=seed.dna.model_dump(mode="json"), first_public_at=observation.published_at.isoformat() if observation.published_at else None,
                           first_seen_at=(previous_event.first_seen_at if previous_event else observation.first_seen_at).isoformat(),
                           last_material_update_at=material_at.isoformat(), evidence_refs=[e_ref], revision_reason="原始观察追加；不执行状态转换",
                           supersedes_version=previous_event.version if previous_event else None), event_inputs)
            self._put(conn, batch, "EventLedgerEntry", "LED:" + seed.event_id, ev,
                      dict(event_ref=event_ref, previous_version=previous_event.version if previous_event else None,
                           operation="APPEND" if previous_event else "CREATE", idempotency_key=batch), [event_ref])
            self.fault("after_ledger")
            self.fault("before_outbox")
            self._put(conn, batch, "OutboxJob", "OUT:" + digest(logical), 1,
                      dict(event_ref=event_ref, job_status="PENDING", effect_key=batch), [event_ref])

        fresh = self._write(key, fingerprint, build)
        if not fresh:
            self._duplicate_decision(key)
        with self.engine.connect() as conn:
            rows = conn.execute(select(records).where(records.c.batch_id == key, records.c.kind == "EvidenceVersion")).mappings().all()
        return self.get(rows[0]["object_id"], rows[0]["version"])

    @staticmethod
    def _decode_observation(data):
        return c.RawObservation.model_validate({**{k: v for k, v in data.items() if k != "raw_hex"}, "raw": bytes.fromhex(data["raw_hex"])})

    def reception_version(self, observation):
        """采集内容版本由最后已保存版本推进；A→B→A仍保留第三版。"""
        identity = "EVD:" + digest([observation.source_ref.object_id, observation.locator])
        prior = max((r for r in self.history(as_of=self.now(), kind="EvidenceVersion") if r.object_id == identity),
                    key=lambda r: r.version, default=None)
        data = observation.model_dump()
        if prior and prior.raw_content_hash == digest(observation.raw):
            with self.engine.connect() as conn:
                payload = conn.execute(select(records.c.payload).where(records.c.object_id == "OBS:" + prior.raw_object_ref)).scalar_one()
            old = self._decode_observation(json.loads(payload))
            return c.RawObservation.model_validate({**old.model_dump(), "first_seen_at": observation.first_seen_at,
                                                    "collected_at": observation.collected_at})
        data["content_version"] = str(prior.version + 1 if prior else 1) + ":" + digest(observation.raw)
        data["change_type"] = "EDIT" if prior else "INITIAL"
        return c.RawObservation.model_validate(data)

    def _duplicate_decision(self, batch):
        with self.engine.connect() as conn:
            row = conn.execute(select(records).where(records.c.batch_id == batch, records.c.kind == "EvidenceVersion")).mappings().one()
        e_ref = dict(object_id=row["object_id"], version=row["version"])
        self._write("DUP:" + batch, digest(e_ref), lambda conn, view, key:
                    self._put(conn, key, "NoveltyDecision", "DUP:" + batch, 1,
                              dict(classification="R0", evidence_ref=e_ref, evidence_refs=[e_ref], reason_codes=["EXACT_DUPLICATE"]), [e_ref]))

    def confirm_origin(self, origin_ids, evidence_refs, *, confirmation_key, confirmation_ref, proof_span):
        """人工核验的强证据链追加确认；不覆盖旧簇，也不重写旧时点计数。"""
        origin_ids = sorted(set(origin_ids))
        if len(origin_ids) < 2 or not evidence_refs:
            raise ValueError("ORIGIN_PROOF：合源需至少两个簇及具体证据")
        refs = [r.model_dump() for r in evidence_refs] + [confirmation_ref.model_dump()]
        def build(conn, view, key):
            covered = {view[(r.object_id, r.version)].origin_cluster_id for r in evidence_refs
                       if isinstance(view.get((r.object_id, r.version)), EvidenceVersion)}
            if not set(origin_ids) <= covered:
                raise ValueError("ORIGIN_PROOF：确认引用未覆盖所有待合并簇")
            proof = view.get((confirmation_ref.object_id, confirmation_ref.version))
            if not isinstance(proof, EvidenceVersion):
                raise ValueError("ORIGIN_PROOF：缺少后来确认转载链的证据")
            raw = conn.execute(select(raw_archive.c.raw_bytes).where(raw_archive.c.raw_id == proof.raw_object_ref)).scalar_one()
            if not proof_span or proof_span not in raw.decode("utf-8", errors="replace"):
                raise ValueError("ORIGIN_PROOF：确认引用片段不在原始证据中")
            for evidence_ref in evidence_refs:
                evidence = view[(evidence_ref.object_id, evidence_ref.version)]
                if evidence.source_id not in proof_span or evidence.canonical_url_or_locator not in proof_span:
                    raise ValueError("ORIGIN_PROOF：确认片段缺少具体来源和原始定位")
            identity = "MERGE:" + digest(origin_ids)
            version = max((r.version for r in view.values() if r.object_id == identity), default=0) + 1
            self._put(conn, key, "OriginClusterVersion", identity, version,
                      dict(member_origin_ids=origin_ids, basis="CONFIRMED_SAME_ORIGIN", verification="KNOWN_ORIGIN",
                           evidence_refs=refs, confirmation_ref=confirmation_ref.model_dump(), proof_span=proof_span,
                           reason_codes=["REVIEWED_EXPLICIT_ORIGIN_CHAIN"]), refs)
        self._write("CONFIRM:" + confirmation_key, digest([origin_ids, refs, proof_span]), build)

    def origin_summary(self, *, as_of, event_id):
        history = self.history(as_of=as_of)
        evidence_ids = {(r.object_id, r.version) for e in history if isinstance(e, EventVersion) and e.event_id == event_id
                        for r in e.evidence_refs}
        origins = {e.origin_cluster_id for e in history if isinstance(e, EvidenceVersion) and (e.object_id, e.version) in evidence_ids}
        groups = [{o} for o in origins]
        known = set()
        for cluster in history:
            if not isinstance(cluster, c.OriginClusterVersion):
                continue
            members = set(cluster.member_origin_ids)
            if cluster.verification == "KNOWN_ORIGIN":
                known.update(members)
            if cluster.basis == "CONFIRMED_SAME_ORIGIN":
                joined = [g for g in groups if g & members]
                groups = [g for g in groups if not g & members]
                if joined:
                    groups.append(set().union(*joined))
        # 使用证据当时引用的来源版本，后来的身份验证不得升级旧证据。
        sources = {(s.object_id, s.version): s for s in history if isinstance(s, Source)}
        roots = {}
        for evidence in history:
            if not isinstance(evidence, EvidenceVersion) or evidence.is_first_hand is not True:
                continue
            source = sources.get((evidence.source_ref.object_id, evidence.source_ref.version))
            if (source is not None and source.source_id == evidence.source_id
                    and source.identity_status == "VERIFIED"
                    and source.status not in ("HOLD", "QUARANTINED")
                    and evidence.quality_status == "VALIDATED"
                    and evidence.status not in ("HOLD", "QUARANTINED")):
                roots.setdefault(evidence.origin_cluster_id, set()).add(source.source_id)
        units = []
        resolved = origins <= known
        for group in groups:
            identities = set().union(*(roots.get(origin, set()) for origin in group))
            if not identities:
                resolved = False
                continue
            # 已确认同源的一组最多贡献一个独立单元；跨Origin共享source_id也只算一次。
            joined = [unit for unit in units if unit & identities]
            units = [unit for unit in units if not unit & identities]
            units.append(identities.union(*joined))
        return dict(origin_count=len(groups), independent_source_count=len(units) if resolved else None,
                    status="KNOWN_ORIGIN_COUNT" if resolved else "HOLD_INDEPENDENCE_UNKNOWN")

    def complete_outbox(self, job_id, result_zh, *, completion_key=None):
        """仅演示数据库内幂等消费确认；不调用外部副作用。"""
        original = self.get(job_id, 1)
        if not isinstance(original, c.OutboxJob):
            raise ValueError("OUTBOX_MISSING")
        key = "OUTBOX_DONE:" + (completion_key or job_id)
        def build(conn, view, batch):
            if self.now() < original.available_at:
                raise ValueError("PIT_OUTBOX：任务输入尚不可用")
            existing = [r for r in view.values() if r.object_id == job_id and r.version > 1]
            if existing:
                raise ValueError("OUTBOX_ALREADY_DONE：使用原effect key重试")
            self._put(conn, batch, "OutboxJob", job_id, 2,
                      dict(event_ref=original.event_ref.model_dump(), job_status="DONE", effect_key=original.effect_key,
                           result_zh=result_zh, supersedes_version=1), [ref(original)])
        self._write(key, digest([job_id, result_zh]), build)
        return self.get(job_id, 2)

    def collector_result(self, source_ref, *, attempt_key, attempted_at, received_at=None, success=False,
                         detail_zh, cursor=None, since_id=None, etag=None, last_modified=None, authorization_hold=False,
                         received_evidence_refs=(), not_modified=False):
        """仅在调用者已保存本次响应后推进游标；失败保持最后成功位置。"""
        attempted_at = TypeAdapter(UTCDateTime).validate_python(attempted_at)
        received_at = TypeAdapter(UTCDateTime).validate_python(received_at) if received_at else None
        if received_at and received_at < attempted_at:
            raise ValueError("PIT_CURSOR：接收早于尝试")
        identity = "CURSOR:" + source_ref.object_id
        def build(conn, view, key):
            source = view.get((source_ref.object_id, source_ref.version))
            if not isinstance(source, Source):
                raise ValueError("SOURCE_MISSING")
            old = max((r for r in view.values() if r.object_id == identity), key=lambda r: r.version, default=None)
            if success:
                if not_modified:
                    if old is None or old.last_success_at is None:
                        raise ValueError("CURSOR_304：无历史成功位置不能采用304")
                elif not received_evidence_refs:
                    raise ValueError("CURSOR_UNSAVED：必须先保存本次原始响应才能推进Cursor")
                for evidence_ref in received_evidence_refs:
                    evidence = view.get((evidence_ref.object_id, evidence_ref.version))
                    if not isinstance(evidence, EvidenceVersion) or evidence.source_id != source.source_id:
                        raise ValueError("CURSOR_UNSAVED：响应引用必须是本来源已提交Evidence")
            if max(attempted_at, received_at or attempted_at) > self.now():
                raise ValueError("PIT_CURSOR：采集结果来自未来")
            ver = old.version + 1 if old else 1
            payload = dict(source_id=source.source_id, last_attempt_at=attempted_at.isoformat(),
                           last_received_at=(received_at or (old.last_received_at if old else None)),
                           last_success_at=(received_at or self.now()) if success else (old.last_success_at if old else None),
                           cursor=cursor if success else (old.cursor if old else None),
                           since_id=since_id if success else (old.since_id if old else None),
                           etag=etag if success else (old.etag if old else None),
                           last_modified=last_modified if success else (old.last_modified if old else None))
            payload = json.loads(json.dumps(payload, default=lambda v: v.isoformat()))
            inputs = [ref(source)] + ([ref(old)] if old else []) + [r.model_dump() for r in received_evidence_refs]
            self._put(conn, key, "CollectorCursor", identity, ver, payload, inputs)
            self._put(conn, key, "SourceHealth", "HEALTH:" + source.source_id, ver,
                      dict(source_id=source.source_id, health="OK" if success else ("AUTHORIZATION_HOLD" if authorization_hold else "SOURCE_UNAVAILABLE"),
                           last_attempt_at=attempted_at.isoformat(), detail_zh=detail_zh), inputs)
        fingerprint = digest([source_ref.model_dump(), attempted_at.isoformat(), received_at.isoformat() if received_at else None,
                              success, cursor, since_id, etag, last_modified, detail_zh, authorization_hold,
                              [r.model_dump() for r in received_evidence_refs], not_modified])
        self._write("COLLECT:" + attempt_key, fingerprint, build)
