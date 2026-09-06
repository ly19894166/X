"""失败只降级一个来源；保存响应成功后才推进该来源游标。"""
from ..adapters.http import AuthorizationHold, SourceUnavailable
from ..contracts.common import VersionRef
from ..ledger.contracts import CollectorCursor
from ..ledger.store import ref


def collect_once(ledger, adapter, source, seed, *, attempt_key, rss=False):
    if ledger.get(source.object_id, source.version) != source:
        raise ValueError("SOURCE_VERSION_CONFLICT：采集配置必须与已登记具体来源版本一致")
    attempted = ledger.now()
    cursors = [r for r in ledger.history(as_of=attempted, kind="CollectorCursor") if r.source_id == source.source_id]
    previous = max(cursors, key=lambda r: r.version) if cursors else None
    try:
        result = adapter.fetch(source, etag=previous.etag if previous else None,
                               last_modified=previous.last_modified if previous else None, rss=rss,
                               change_type="EDIT" if previous and previous.last_success_at else "INITIAL")
        evidence_refs = []
        if result.observation is not None:
            evidence = ledger.ingest(ledger.reception_version(result.observation), seed)
            evidence_refs.append(VersionRef(**ref(evidence)))
        ledger.collector_result(VersionRef(**ref(source)), attempt_key=attempt_key, attempted_at=attempted,
                                received_at=result.received_at, success=True, detail_zh="CURRENT_OBSERVATION_ONLY：未验收历史PIT",
                                etag=result.etag, last_modified=result.last_modified,
                                received_evidence_refs=evidence_refs, not_modified=result.not_modified)
        return dict(status="CURRENT_OBSERVATION_ONLY", entries=result.entries)
    except (AuthorizationHold, SourceUnavailable) as exc:
        ledger.collector_result(VersionRef(**ref(source)), attempt_key=attempt_key, attempted_at=attempted,
                                success=False, detail_zh=str(exc), authorization_hold=isinstance(exc, AuthorizationHold))
        return dict(status="AUTHORIZATION_HOLD" if isinstance(exc, AuthorizationHold) else "SOURCE_UNAVAILABLE", entries=())
