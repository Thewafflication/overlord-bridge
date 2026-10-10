"""Collect bridge tests without operator credentials or runtime files."""

import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Set before test modules import bridge and its configuration constants.
# These values are deliberately invalid credentials and never start a bot.
os.environ["TELEGRAM_BOT_TOKEN"] = "offline-test-token"
os.environ["OWNER_CHAT_ID"] = "42"


@pytest.fixture(autouse=True)
def block_offline_network(monkeypatch, request):
    """Fail external connections while preserving asyncio's local sockets."""
    if request.node.get_closest_marker("live"):
        return

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked(connection, address, *, original):
        if connection.family == getattr(socket, "AF_UNIX", None):
            return original(connection, address)
        if isinstance(address, tuple) and address[0] in (
            "127.0.0.1", "::1", "localhost"
        ):
            return original(connection, address)
        raise RuntimeError("Network access is forbidden in offline tests")

    monkeypatch.setattr(
        socket.socket, "connect",
        lambda conn, addr: blocked(conn, addr, original=original_connect),
    )
    monkeypatch.setattr(
        socket.socket, "connect_ex",
        lambda conn, addr: blocked(conn, addr, original=original_connect_ex),
    )
