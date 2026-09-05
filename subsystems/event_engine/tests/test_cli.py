import json
import subprocess
import sys
from pathlib import Path

import pytest

from xevent.cli import main

FIXTURE = Path(__file__).parents[1] / "configs" / "offline_fixture.zh-CN.json"


def test_cli_offline_entrypoint():
    result = subprocess.run([sys.executable, "-m", "xevent.cli", "ingest", "--fixture", str(FIXTURE)],
                            capture_output=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 0 and "校验通过：9 个版本" in result.stdout


def test_cli_schema_export(tmp_path):
    path = tmp_path / "schema.json"
    assert main(["schema", "--model", "EvidenceVersion", "--output", str(path)]) == 0
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert {"ready_at", "recorded_at", "available_at"} <= set(schema["required"])


@pytest.mark.pit
def test_cli_asof_hold_then_visible(capsys):
    args = ["inspect", "--fixture", str(FIXTURE), "--event-id", "EV_001", "--as-of"]
    assert main([*args, "2026-09-06T10:00:03+08:00"]) == 3
    assert "HOLD" in capsys.readouterr().out
    assert main([*args, "2026-09-06T10:00:08+08:00"]) == 0
    assert "虚构供电试点研究意向" in capsys.readouterr().out


def test_cli_error_chinese(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"sources": []}', encoding="utf-8")
    assert main(["ingest", "--fixture", str(path)]) == 2
    assert "校验失败" in capsys.readouterr().err
    assert main(["ingest", "--fixture", str(tmp_path / "missing")]) == 2
    assert "FAIL_CLOSED" in capsys.readouterr().err


def test_cli_forbidden_service_command(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--daemon"])
    assert exc.value.code == 2
    assert "参数错误" in capsys.readouterr().err
