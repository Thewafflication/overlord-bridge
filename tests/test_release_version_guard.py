from pathlib import Path

import pytest

from tools import check_release_version as guard


def source(tmp_path, project="1.2.3", fallback="1.2.3"):
    (tmp_path / "modules").mkdir()
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{project}"\n')
    (tmp_path / "modules/version.py").write_text(f'FALLBACK_VERSION = "{fallback}"\n')
    return tmp_path


@pytest.mark.parametrize("tag", ["1.2.3", "v1.2.3"])
def test_matching_tag_and_runtime_are_accepted(tmp_path, tag):
    assert guard.verify(source(tmp_path), tag) == "1.2.3"


@pytest.mark.parametrize("project,fallback", [("1.2.2", "1.2.2"), ("1.2.3", "1.2.2")])
def test_tagged_release_cannot_keep_stale_runtime_metadata(tmp_path, project, fallback):
    with pytest.raises(ValueError, match="mismatch"):
        guard.verify(source(tmp_path, project, fallback), "v1.2.3")


def test_version_sources_are_inspected_without_executing_them(tmp_path):
    root = source(tmp_path)
    marker = root / "must-not-exist"
    (root / "modules/version.py").write_text(
        f'from pathlib import Path\nPath({str(marker)!r}).touch()\nFALLBACK_VERSION = dynamic()\n')
    with pytest.raises(ValueError, match="mismatch"):
        guard.verify(root, "1.2.3")
    assert not marker.exists()


@pytest.mark.parametrize("tag", ["", "latest", "v1.2", "1.2.3;echo bad"])
def test_invalid_release_inputs_are_rejected(tmp_path, tag):
    with pytest.raises(ValueError, match="semantic"):
        guard.verify(tmp_path, tag)


def test_release_cli_failure_is_nonzero_and_actionable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(guard, "ROOT", source(tmp_path))
    assert guard.main(["v1.2.4"]) == 1
    assert "Update both source versions before tagging" in capsys.readouterr().err
    assert guard.main(["v1.2.3"]) == 0
