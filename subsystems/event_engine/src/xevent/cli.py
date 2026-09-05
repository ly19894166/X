"""Phase 1 离线 CLI；任何命令均不联网、不持久化业务记录。"""
import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .contracts import SCHEMAS
from .contracts.bundle import OfflineFixture
from .contracts.common import PITError, PITQuery


class ChineseParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, f"参数错误：请检查命令、路径和必填参数（{message}）\n")


def main(argv=None):
    parser = ChineseParser(description="X 事件引擎 Phase 1：离线契约校验与 Schema 导出")
    sub = parser.add_subparsers(dest="command", required=True, title="命令")
    ingest = sub.add_parser("ingest", help="校验离线 fixture；不写入数据库")
    ingest.add_argument("--fixture", type=Path, required=True, help="中文 JSON fixture 路径")
    inspect = sub.add_parser("inspect", help="按事件及知识截止时点检查 fixture")
    inspect.add_argument("--fixture", type=Path, required=True, help="JSON fixture 路径")
    inspect.add_argument("--event-id", required=True, help="固定事件 ID")
    inspect.add_argument("--as-of", required=True, help="带时区的知识截止时间")
    inspect.add_argument("--mode", choices=("LIVE_FORWARD", "OBSERVED_REPLAY", "PUBLIC_PIT_RESEARCH"), default="LIVE_FORWARD", help="研究模式；历史模拟隔离")
    schema = sub.add_parser("schema", help="使用 Pydantic 导出 JSON Schema")
    schema.add_argument("--model", choices=tuple(SCHEMAS) + ("OfflineFixture",), required=True, help="契约名称")
    schema.add_argument("--output", type=Path, help="输出文件；省略时显示 JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            model = OfflineFixture if args.model == "OfflineFixture" else SCHEMAS[args.model]
            result = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
            if args.output:
                args.output.write_text(result, encoding="utf-8")
                print(f"已导出：{args.output}")
            else:
                print(result, end="")
            return 0
        fixture = OfflineFixture.model_validate_json(args.fixture.read_text(encoding="utf-8-sig"))
        if args.command == "ingest":
            print(f"校验通过：{len(list(fixture.records()))} 个版本；离线校验，未持久化。")
            return 0
        query = PITQuery(as_of=args.as_of, mode=args.mode)
        events = [r for r in fixture.event_versions if r.event_id == args.event_id and r.is_visible(query)]
        if not events:
            print("HOLD：截止时点无可见事件版本。")
            return 3
        print(json.dumps([r.model_dump(mode="json") for r in events], ensure_ascii=False, indent=2))
        return 0
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(p) for p in error["loc"]) or "记录"
            print(f"校验失败 [{error['type']}] {location}：字段类型、枚举、时间或引用不符合契约；{error['msg']}", file=sys.stderr)
        return 2
    except (OSError, ValueError, PITError) as exc:
        print(f"FAIL_CLOSED：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
