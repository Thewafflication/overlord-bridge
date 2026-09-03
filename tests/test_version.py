"""The single version source used by Telegram, the tray, and the console."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import version as v  # noqa: E402


def test_the_version_matches_what_pyproject_declares():
    declared = None
    in_project = False
    for raw in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("["):
            in_project = line == "[project]"
        elif in_project and line.startswith("version"):
            declared = line.partition("=")[2].strip().strip('"').strip("'")
            break
    assert declared, "pyproject.toml must declare a [project] version"
    assert v._from_pyproject() == declared


def test_the_fallback_matches_the_declared_version():
    """Catch the drift that let pyproject sit at 0.1.0 through four releases."""
    assert v.FALLBACK_VERSION == v._from_pyproject()


def test_a_missing_pyproject_falls_back_instead_of_crashing(monkeypatch, tmp_path):
    monkeypatch.setattr(v, "PROJECT_ROOT", tmp_path)
    assert v._from_pyproject() is None
    monkeypatch.setattr(v, "_from_metadata", lambda: None)
    assert v.base_version() == v.FALLBACK_VERSION


def test_the_source_tree_wins_over_stale_installed_metadata(monkeypatch):
    """An editable install's egg-info goes stale; pyproject.toml does not."""
    monkeypatch.setattr(v, "_from_metadata", lambda: "0.1.0")
    monkeypatch.setattr(v, "_from_pyproject", lambda: "1.0.5")
    assert v.base_version() == "1.0.5"


def test_metadata_is_used_when_there_is_no_source_tree(monkeypatch):
    monkeypatch.setattr(v, "_from_pyproject", lambda: None)
    monkeypatch.setattr(v, "_from_metadata", lambda: "9.9.9")
    assert v.base_version() == "9.9.9"


def test_a_git_checkout_appends_the_short_revision(monkeypatch):
    monkeypatch.setattr(v, "_from_pyproject", lambda: "1.2.3")
    monkeypatch.setattr(v, "git_revision", lambda short=7: "abc1234")
    assert v.version_string() == "1.2.3+abc1234"
    assert v.display_version() == "v1.2.3+abc1234"


def test_a_release_without_git_reports_a_bare_version(monkeypatch):
    monkeypatch.setattr(v, "_from_pyproject", lambda: "1.2.3")
    monkeypatch.setattr(v, "git_revision", lambda short=7: None)
    assert v.version_string() == "1.2.3"


def test_the_revision_is_read_from_a_detached_head(monkeypatch, tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("a" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(v, "PROJECT_ROOT", tmp_path)
    assert v.git_revision() == "aaaaaaa"


def test_the_revision_is_read_from_a_branch_ref(monkeypatch, tmp_path):
    git_dir = tmp_path / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "refs" / "heads" / "main").write_text("b" * 40, encoding="utf-8")
    monkeypatch.setattr(v, "PROJECT_ROOT", tmp_path)
    assert v.git_revision() == "bbbbbbb"


def test_the_revision_is_read_from_packed_refs_after_a_gc(monkeypatch, tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "packed-refs").write_text(
        "# pack-refs with: peeled\n" + "c" * 40 + " refs/heads/main\n", encoding="utf-8"
    )
    monkeypatch.setattr(v, "PROJECT_ROOT", tmp_path)
    assert v.git_revision() == "ccccccc"


def test_no_git_directory_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(v, "PROJECT_ROOT", tmp_path)
    assert v.git_revision() is None
