"""Check failures must prevent reporting a successful build or test run."""

import importlib.util
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest


PATH = Path(__file__).resolve().parents[1] / "tools/check.py"
SPEC = importlib.util.spec_from_file_location("project_checks", PATH)
CHECKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKS)


def test_offline_network_access_fails_before_connecting():
    with socket.socket() as connection:
        with pytest.raises(RuntimeError, match="forbidden"):
            connection.connect(("192.0.2.1", 1))


def test_missing_build_tool_is_not_a_success(monkeypatch):
    def missing(*args, **kwargs):
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(CHECKS.subprocess, "run", missing)
    assert CHECKS.run("build") == 1


def test_all_checks_stop_on_failure(monkeypatch):
    called = []

    def failed(stage):
        called.append(stage)
        return 7

    monkeypatch.setattr(CHECKS, "run", failed)
    monkeypatch.setattr(CHECKS.sys, "argv", [str(PATH), "all"])
    assert CHECKS.main() == 7
    assert called == ["lint"]


def test_invalid_owned_source_fails_lint(monkeypatch, tmp_path):
    (tmp_path / "bridge.py").write_text("def invalid(\n", encoding="utf-8")
    monkeypatch.setattr(CHECKS, "ROOT", tmp_path)
    assert CHECKS.lint() == 1
