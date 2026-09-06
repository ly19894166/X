from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys

import pytest
from sqlalchemy import select

from xevent.contracts import Source
from xevent.contracts.common import VersionRef
from xevent.ledger.contracts import EventSeed, RawObservation
from xevent.ledger.schema import batches, raw_archive, receipts, records
from xevent.ledger.store import Ledger, ref


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 6, 4, tzinfo=timezone.utc)

    def __call__(self):
        self.value += timedelta(milliseconds=1)
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


@pytest.fixture
def setup_ledger(tmp_path, payload):
    clock = Clock()
    ledger = Ledger(tmp_path / "event.db", clock=clock)
    source = Source.model_validate({**payload["sources"][0], "identity_status": "VERIFIED"})
    source = ledger.register_source(source)
    seed = EventSeed(event_id="EVENT_P2", title_zh="虚构政策观察", dna={**payload["event_versions"][0]["dna"], "actor_refs": []})
    yield ledger, clock, source, seed
    ledger.close()


def obs(clock, source, text="虚构政策A", version="1", **changes):
    return RawObservation(source_ref=ref(source), locator="fixture:policy", raw=text.encode(),
                          first_seen_at=clock(), collected_at=clock(), content_version=version, **changes)


def test_sqlite_pragmas_and_idempotent_migration(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    with ledger.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 2
        assert conn.exec_driver_sql("PRAGMA user_version").scalar() == 1
    ledger.close()
    other = Ledger(ledger.path, clock=clock)
    assert other.get(source.object_id, 1) == source
    other.close()


def test_ingest_and_exact_duplicate_100_times(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    observation = obs(clock, source)
    first = ledger.ingest(observation, seed)
    for _ in range(100):
        assert ledger.ingest(observation, seed) == first
    assert len(ledger.history(as_of=clock(), kind="EvidenceVersion")) == 1
    assert len(ledger.history(as_of=clock(), kind="EventVersion")) == 1
    assert len(ledger.history(as_of=clock(), kind="OutboxJob")) == 1
    assert {r.classification for r in ledger.history(as_of=clock(), kind="NoveltyDecision")} == {"R0", "UNDETERMINED"}


@pytest.mark.parametrize("stage", ["after_raw", "after_evidence", "after_ledger", "before_outbox", "before_commit", "after_commit", "before_receipt_commit", "after_receipt_commit"])
def test_crash_and_restart_no_partial_publication(setup_ledger, stage):
    ledger, clock, source, seed = setup_ledger
    observation = obs(clock, source)
    def crash(at):
        if at == stage:
            raise RuntimeError("模拟崩溃")
    ledger.fault = crash
    with pytest.raises(RuntimeError, match="模拟崩溃"):
        ledger.ingest(observation, seed)
    cutoff = clock()
    assert not ledger.history(as_of=cutoff, kind="EventVersion")
    assert not ledger.history(as_of=cutoff, kind="OutboxJob")
    ledger.close()
    clock.advance(seconds=10)
    recovered = Ledger(ledger.path, clock=clock)
    evidence = recovered.ingest(observation, seed)
    assert len(recovered.history(as_of=clock(), kind="EvidenceVersion")) == 1
    assert len(recovered.history(as_of=clock(), kind="EventVersion")) == 1
    assert len(recovered.history(as_of=clock(), kind="OutboxJob")) == 1
    assert recovered.raw(evidence.raw_object_ref) == observation.raw
    if stage in ("after_commit", "before_receipt_commit", "after_receipt_commit"):
        assert not recovered.history(as_of=cutoff, kind="EventVersion")
    recovered.close()


def test_append_only_and_tamper_fail_closed(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    evidence = ledger.ingest(obs(clock, source), seed)
    with pytest.raises(Exception, match="APPEND_ONLY"):
        with ledger.engine.begin() as conn:
            conn.execute(raw_archive.update().values(raw_bytes=b"tampered"))
    # 模拟绕过DB保护后的磁盘破坏，读取仍必须发现。
    with ledger.engine.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER immutable_raw_archive_update")
        conn.execute(raw_archive.update().values(raw_bytes=b"tampered"))
    with pytest.raises(ValueError, match="RAW_HASH"):
        ledger.raw(evidence.raw_object_ref)


@pytest.mark.pit
def test_edit_delete_history_and_replay_deterministic(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    v1 = ledger.ingest(obs(clock, source, "原文V1"), seed)
    cutoff = clock()
    before = ledger.replay(cutoff)
    for version, text, change in (("2", "编辑V2", "EDIT"), ("3", "编辑V3", "EDIT"), ("4", "", "DELETE")):
        clock.advance(minutes=10)
        ledger.ingest(obs(clock, source, text, version, change_type=change), seed)
    assert ledger.replay(cutoff) == before == ledger.replay(cutoff)
    assert ledger.raw(v1.raw_object_ref) == "原文V1".encode()
    changes = ledger.history(as_of=clock(), kind="EvidenceChange")
    assert [r.change_type for r in changes] == ["INITIAL", "EDIT", "EDIT", "DELETE"]
    assert [r.version for r in ledger.history(as_of=clock(), kind="EvidenceVersion")] == [1, 2, 3, 4]
    ledger.close()
    restarted = Ledger(ledger.path, clock=clock)
    assert restarted.replay(cutoff) == before
    restarted.close()


@pytest.mark.pit
def test_late_old_article_preserves_observed_time(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    cutoff = clock()
    published = datetime(2020, 1, 1, tzinfo=timezone.utc)
    observation = obs(clock, source, published_at=published)
    evidence = ledger.ingest(observation, seed)
    assert evidence.first_seen_at == observation.first_seen_at
    assert evidence.collected_at == observation.collected_at
    assert evidence.available_at > cutoff
    assert not ledger.history(as_of=cutoff, kind="EvidenceVersion")


def test_origin_one_official_twenty_media_fifty_reposts(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    original = ledger.ingest(obs(clock, source, is_first_hand=True), seed)
    for n in range(70):
        media = Source.model_validate({**source.model_dump(), "object_id": f"SRC_{n}", "source_id": f"SRC_{n}",
                                      "canonical_locator": f"fixture:media:{n}"})
        media = ledger.register_source(media)
        observation = obs(clock, media, f"第{n}家转述的不同文字", origin_ref=VersionRef(**ref(original)))
        ledger.ingest(observation, seed)
    summary = ledger.origin_summary(as_of=clock(), event_id=seed.event_id)
    assert summary["origin_count"] == summary["independent_source_count"] == 1
    assert sum(r.classification == "R1" for r in ledger.history(as_of=clock(), kind="NoveltyDecision")) == 70


@pytest.mark.pit
def test_similar_policy_not_merged_and_later_confirmation_is_versioned(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    first = ledger.ingest(obs(clock, source, "政策A：补贴1亿元"), seed)
    other = Source.model_validate({**source.model_dump(), "object_id": "S2", "source_id": "S2"})
    other = ledger.register_source(other)
    second = ledger.ingest(obs(clock, other, "政策B：补贴2亿元"), seed)
    cutoff = clock()
    initial = ledger.origin_summary(as_of=cutoff, event_id=seed.event_id)
    assert initial["origin_count"] == 2 and initial["independent_source_count"] is None
    clock.advance(minutes=30)
    proof_span = f"{first.source_id} {first.canonical_url_or_locator} 与 {second.source_id} {second.canonical_url_or_locator} 是同一原始消息的转载链"
    proof_seed = EventSeed(**{**seed.model_dump(), "event_id": "PROOF_EVENT"})
    proof_obs = obs(clock, source, proof_span, "proof")
    proof_obs = RawObservation.model_validate({**proof_obs.model_dump(), "locator": "fixture:chain-confirmation"})
    proof = ledger.ingest(proof_obs, proof_seed)
    ledger.confirm_origin([first.origin_cluster_id, second.origin_cluster_id],
                          [VersionRef(**ref(first)), VersionRef(**ref(second))], confirmation_key="人工核验链001",
                          confirmation_ref=VersionRef(**ref(proof)), proof_span=proof_span)
    assert ledger.origin_summary(as_of=cutoff, event_id=seed.event_id) == initial
    assert ledger.origin_summary(as_of=clock(), event_id=seed.event_id)["origin_count"] == 1


@pytest.mark.pit
def test_outbox_idempotent_after_input_available(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    ledger.ingest(obs(clock, source), seed)
    job = ledger.history(as_of=clock(), kind="OutboxJob")[0]
    cutoff = clock()
    clock.advance(seconds=10)
    done = ledger.complete_outbox(job.object_id, "离线消费完成")
    assert ledger.complete_outbox(job.object_id, "离线消费完成") == done
    assert done.available_at > job.available_at
    assert [r.job_status for r in ledger.history(as_of=cutoff, kind="OutboxJob")] == ["PENDING"]


@pytest.mark.pit
def test_cursor_restart_and_failure_does_not_move_success(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    attempted = clock()
    observation = obs(clock, source)
    received = observation.collected_at
    evidence = ledger.ingest(observation, seed)
    ledger.collector_result(VersionRef(**ref(source)), attempt_key="c1", attempted_at=attempted, received_at=received,
                            success=True, detail_zh="测试", cursor="001", etag="v1",
                            received_evidence_refs=[VersionRef(**ref(evidence))])
    cutoff = clock()
    before = ledger.history(as_of=cutoff, kind="CollectorCursor")[0]
    ledger.close()
    restarted = Ledger(ledger.path, clock=clock)
    restarted.collector_result(VersionRef(**ref(source)), attempt_key="c2", attempted_at=clock(), success=False, detail_zh="超时")
    latest = restarted.history(as_of=clock(), kind="CollectorCursor")[-1]
    assert latest.cursor == before.cursor == "001"
    assert latest.last_received_at == received and latest.last_success_at == before.last_success_at
    assert restarted.history(as_of=cutoff, kind="CollectorCursor") == [before]
    restarted.close()


@pytest.mark.pit
def test_novelty_later_structured_classification_does_not_backfill(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    ledger.ingest(obs(clock, source, json.dumps({"amount": "1", "legal_status": "draft"}), structured_fields={"amount": "1", "legal_status": "draft"},
                      structured_basis="SOURCE_STRUCTURED"), seed)
    cutoff = clock()
    old = ledger.history(as_of=cutoff, kind="NoveltyDecision")
    for version, fields, expected in (
            ("2", {"amount": "2", "legal_status": "draft"}, "R3"),
            ("3", {"amount": "2", "legal_status": "law"}, "R4"),
            ("4", {"amount": "2", "legal_status": "law", "retracted": "true"}, "R5")):
        clock.advance(minutes=10)
        ledger.ingest(obs(clock, source, json.dumps(fields), version, change_type="EDIT", structured_fields=fields,
                          structured_basis="SOURCE_STRUCTURED", is_first_hand=True), seed)
        assert ledger.history(as_of=clock(), kind="NoveltyDecision")[-1].classification == expected
    assert ledger.history(as_of=cutoff, kind="NoveltyDecision") == old


def test_idempotency_conflict_rolls_back(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    ledger.ingest(obs(clock, source), seed)
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        ledger.ingest(obs(clock, source, "同版本不同内容"), seed)
    assert len(ledger.history(as_of=clock(), kind="EventVersion")) == 1


@pytest.mark.parametrize("stage", ["after_raw", "after_commit"])
def test_real_process_exit_and_wal_recovery(setup_ledger, tmp_path, stage):
    ledger, clock, source, seed = setup_ledger
    observation = obs(clock, source)
    data = {"source_ref": ref(source), "seed": seed.model_dump(mode="json"),
            "observation": {**observation.model_dump(mode="json", exclude={"raw"}), "raw_hex": observation.raw.hex()}}
    path = tmp_path / "crash-input.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    child_time = clock.value + timedelta(hours=1)
    script = """
import json, os, sys
from datetime import datetime
from xevent.ledger.store import Ledger
from xevent.ledger.contracts import EventSeed
data=json.load(open(sys.argv[2],encoding='utf-8'))
def fault(stage):
    if stage==sys.argv[3]: os._exit(77)
db=Ledger(sys.argv[1],clock=lambda:datetime.fromisoformat(sys.argv[4]),fault=fault)
db.ingest(db._decode_observation(data['observation']),EventSeed.model_validate(data['seed']))
"""
    result = subprocess.run([sys.executable, "-c", script, str(ledger.path), str(path), stage, child_time.isoformat()])
    assert result.returncode == 77
    assert not ledger.history(as_of=child_time, kind="EventVersion")
    clock.value = child_time + timedelta(minutes=1)
    ledger.fault = lambda stage: None
    ledger.recover()
    evidence = ledger.ingest(observation, seed)
    assert len(ledger.history(as_of=clock(), kind="EventVersion")) == 1
    assert ledger.raw(evidence.raw_object_ref) == observation.raw


@pytest.mark.pit
def test_recorded_at_observed_after_commit_boundary(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    boundary = []
    def slow_commit(stage):
        if stage == "before_commit":
            clock.advance(seconds=5)
            boundary.append(clock.value)
    ledger.fault = slow_commit
    evidence = ledger.ingest(obs(clock, source), seed)
    assert evidence.recorded_at > boundary[-1]
    assert evidence.available_at >= evidence.recorded_at > evidence.ready_at


@pytest.mark.pit
def test_slow_receipt_commit_does_not_backdate_available_at(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    boundary = []
    def slow_receipt(stage):
        if stage == "before_receipt_commit":
            clock.advance(seconds=7)
            boundary.append(clock.value)
    ledger.fault = slow_receipt
    evidence = ledger.ingest(obs(clock, source), seed)
    assert evidence.available_at > boundary[-1]
    assert not ledger.history(as_of=boundary[-1], kind="EvidenceVersion")


def test_outbox_completion_rollback_is_idempotent(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    ledger.ingest(obs(clock, source), seed)
    job = ledger.history(as_of=clock(), kind="OutboxJob")[0]
    def fault(stage):
        if stage == "before_commit":
            raise RuntimeError("消费回滚")
    ledger.fault = fault
    with pytest.raises(RuntimeError, match="消费回滚"):
        ledger.complete_outbox(job.object_id, "完成")
    assert len(ledger.history(as_of=clock(), kind="OutboxJob")) == 1
    ledger.fault = lambda stage: None
    done = ledger.complete_outbox(job.object_id, "完成")
    assert ledger.complete_outbox(job.object_id, "完成") == done


def test_phase2_cli_offline_fixture_and_replay(tmp_path, capsys):
    from pathlib import Path
    from xevent.cli import main
    fixture = Path(__file__).parents[1] / "configs" / "phase2_observations.zh-CN.json"
    db = tmp_path / "cli.db"
    assert main(["ledger-ingest", "--db", str(db), "--fixture", str(fixture)]) == 0
    capsys.readouterr()
    args = ["ledger-replay", "--db", str(db), "--as-of", "2099-01-01T00:00:00Z"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == first


@pytest.mark.pit
def test_source_future_version_and_hold_cannot_feed_formal_evidence(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    future = Source.model_validate({**source.model_dump(), "version": 2, "available_at": clock.value + timedelta(days=1)})
    with pytest.raises(ValueError, match="PIT_SOURCE"):
        ledger.register_source(future)
    held = ledger.register_source(Source.model_validate({**source.model_dump(), "version": 2, "status": "HOLD", "reason_codes": ["来源身份争议"]}))
    with pytest.raises(ValueError, match="PIT_INPUT"):
        ledger.ingest(obs(clock, held), seed)


def test_cursor_cannot_advance_without_saved_response(setup_ledger):
    ledger, clock, source, seed = setup_ledger
    with pytest.raises(ValueError, match="CURSOR_UNSAVED"):
        ledger.collector_result(VersionRef(**ref(source)), attempt_key="bad", attempted_at=clock(), received_at=clock(),
                                success=True, detail_zh="响应未保存")
    assert not ledger.history(as_of=clock(), kind="CollectorCursor")


def test_migration_refuses_unrelated_database(tmp_path):
    import sqlite3
    path = tmp_path / "unrelated.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated_model(id INTEGER)")
    with pytest.raises(ValueError, match="MIGRATION_HOLD"):
        Ledger(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("unrelated_model",)]
