"""Manual bounded pilot. No live request unless source review and --live both pass."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "subsystems/event_engine/src"))

from xevent.adapters.http import HTTPAdapter
from xevent.contracts.models import Source
from xevent.ledger.contracts import EventSeed
from xevent.ledger.store import Ledger
from xevent.social.contracts import SourceQualification
from xevent.social.pilot import collect_social, review_binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    if not args.runtime.is_absolute() or runtime == ROOT or ROOT in runtime.parents:
        raise ValueError("RUNTIME_MUST_BE_EXTERNAL_ABSOLUTE")
    reviews = [SourceQualification.model_validate(r) for r in json.loads(
        (ROOT / "docs/social_signal/source_qualifications.json").read_text(encoding="utf-8"))]
    if args.live and any(r.qualification_status != "QUALIFIED" for r in reviews):
        raise ValueError("HOLD_SOURCE_AUTHORIZATION: no live request permitted")
    for directory in ("db", "raw", "logs", "reports", "state"):
        (runtime / directory).mkdir(parents=True, exist_ok=True)
    seed = EventSeed(event_id="SOCIAL_SEED", title_zh="社交线索调查",
        dna=dict(actor_refs=[], action_code="SOCIAL_OBSERVATION",
            object_entities=[dict(entity_id="UNRESOLVED_SOCIAL", entity_type="UNRESOLVED", name_zh="未确认社交讨论")],
            domain_ids=["UNKNOWN"], geographic_scope=["UNKNOWN"], temporal_scope="UNKNOWN",
            identity_rule_version="D_SOCIAL_SIGNAL_V0.1"))
    report = {"status": "HOLD", "api_budget": 0, "paid_api_calls": 0, "sources": {}}
    with closing(Ledger(runtime / "db/social.sqlite")) as ledger:
        for review in reviews:
            now = datetime.now(timezone.utc)
            identity = "D_SOURCE:" + review.platform
            existing = [s for s in ledger.history(as_of=now, kind="Source") if s.source_id == identity]
            if existing:
                source = max(existing, key=lambda s: s.version)
                if source.retention_policy != review_binding(review):
                    raise ValueError("SOURCE_REVIEW_CHANGED: register an explicit new source version")
            else:
                qualified = review.qualification_status == "QUALIFIED"
                source = ledger.register_source(Source(object_id=identity, source_id=identity, version=1,
                    recorded_at=now, available_at=now, run_id="D_REGISTER", policy_version="D_SOCIAL_SIGNAL_V0.1",
                    content_hash="0"*64, name_zh=review.source_name, platform=review.platform,
                    canonical_locator=review.endpoint, tier="S4", roles=["NARRATIVE", "DIFFUSION"],
                    access_method="ANONYMOUS_HTTP_GET", retention_policy=review_binding(review),
                    enabled=qualified, terms_status="REVIEWED" if qualified else "UNKNOWN",
                    authorization_status="AUTHORIZED" if qualified else "UNKNOWN",
                    allowed_uses=["EVENT_RESEARCH"] if qualified else [], raw_retention_allowed=True if qualified else None))
            results = []
            if args.live or review.qualification_status != "QUALIFIED":
                with closing(HTTPAdapter(attempts=1)) as adapter:
                    for _ in range(2 if args.live else 1):
                        outcome = collect_social(ledger, adapter, source, review, seed,
                            attempt_key="D_MANUAL:" + str(uuid4()), resume=False)
                        results.append({"status": outcome["status"], "lifecycle": outcome["lifecycle"]})
                        if outcome["status"] != "SOCIAL_LEAD":
                            break
            items = [s for s in ledger.history(as_of=ledger.now(), kind="SocialObservation")
                     if s.platform == review.platform]
            report["sources"][review.platform] = {"results": results,
                "logical_observations": len({s.object_id for s in items}), "versions": len(items)}
    # Engineering/CI and legal gates are independent; this script cannot grant readiness.
    (runtime / "reports/manual-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
