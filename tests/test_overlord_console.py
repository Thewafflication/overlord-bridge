import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent.parent / "tools" / "overlord_console.py"
SPEC = importlib.util.spec_from_file_location("overlord_console", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_log_lines_are_classified_for_rich_text():
    assert MODULE.level_for_line("2026 overlord INFO Ready") == "info"
    assert MODULE.level_for_line("2026 overlord WARNING Retry") == "warning"
    assert MODULE.level_for_line("2026 overlord ERROR Failed") == "error"
    assert MODULE.level_for_line("plain output") == "plain"
