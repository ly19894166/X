import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    import socket
    def blocked(*args, **kwargs):
        raise RuntimeError("TEST_NETWORK_FORBIDDEN：测试只允许mock/fixture")
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture
def payload():
    path = Path(__file__).parents[1] / "configs" / "offline_fixture.zh-CN.json"
    return json.loads(path.read_text(encoding="utf-8"))
