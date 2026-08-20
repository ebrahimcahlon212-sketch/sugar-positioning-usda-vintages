from __future__ import annotations

import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _deny_network(*args: object, **kwargs: object) -> None:
    del args, kwargs
    raise AssertionError("tests must not access the network")


class MonkeyPatchLike(Protocol):
    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None: ...


@pytest.fixture(autouse=True)
def _block_test_network(monkeypatch: MonkeyPatchLike) -> Iterator[None]:
    """Fail closed for common Python socket paths during every test."""

    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", _deny_network)
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.setattr(socket.socket, "sendto", _deny_network)
    yield
