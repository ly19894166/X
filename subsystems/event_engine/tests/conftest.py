import json
from pathlib import Path

import pytest


@pytest.fixture
def payload():
    path = Path(__file__).parents[1] / "configs" / "offline_fixture.zh-CN.json"
    return json.loads(path.read_text(encoding="utf-8"))
