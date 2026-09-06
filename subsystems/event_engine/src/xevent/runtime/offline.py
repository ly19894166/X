"""显式离线持久化入口；接收时间来自虚构fixture，不冒充真实抓取。"""
import json

from sqlalchemy.exc import SQLAlchemyError

from ..contracts import Source
from ..ledger.contracts import EventSeed, RawObservation
from ..ledger.store import Ledger


def ledger_command(args):
    if args.command != "ledger-ingest" and not args.db.is_file():
        raise ValueError("DB_MISSING：请指定已存在的事件数据库")
    ledger = None
    try:
        ledger = Ledger(args.db, recover_on_open=args.command != "ledger-replay")
        if args.command == "ledger-ingest":
            payload = json.loads(args.fixture.read_text(encoding="utf-8-sig"))
            source = ledger.register_source(Source.model_validate(payload["source"]))
            seed = EventSeed.model_validate(payload["event_seed"])
            for item in payload["observations"]:
                item = dict(item)
                raw = item.pop("raw_text").encode("utf-8")
                observation = RawObservation.model_validate({**item, "raw": raw,
                    "source_ref": dict(object_id=source.object_id, version=source.version)})
                ledger.ingest(observation, seed)
            print("离线持久化完成：原始档案、历史、Novelty和Outbox已提交；接收时间为fixture声明。")
        elif args.command == "ledger-replay":
            print(json.dumps(ledger.replay(args.as_of), ensure_ascii=False, indent=2))
        else:
            print("恢复完成：缺回执批次已按恢复时点保守发布；原始接收时间未重写。")
        return 0
    except SQLAlchemyError as exc:
        raise ValueError("SQLITE_FAIL_CLOSED：事务或数据库校验失败") from exc
    except (KeyError, TypeError) as exc:
        raise ValueError("FIXTURE_INVALID：Phase2来源、事件种子或观察字段不完整") from exc
    finally:
        if ledger:
            ledger.close()
