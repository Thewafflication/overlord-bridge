"""REQ-OVL-002: malformed usage must not interrupt reply accounting."""

import pytest

from modules.token_meter import TokenLedger, normalize_usage


@pytest.mark.parametrize("brain", ["claude", "codex"])
@pytest.mark.parametrize(
    "bad", [None, "unknown", {}, [], float("nan"), float("inf"), -10]
)
def test_invalid_input_preserves_known_output(brain, bad, tmp_path):
    keys = (
        ("input_tokens", "output_tokens")
        if brain == "claude"
        else ("inputTokens", "outputTokens")
    )
    usage = normalize_usage(
        {keys[0]: bad, keys[1]: 17}, brain=brain, outcome="stopped"
    )
    assert usage is not None
    assert usage.input_tokens == 0
    assert usage.output_tokens == 17
    assert usage.outcome == "stopped"
    path = tmp_path / "ledger.json"
    TokenLedger(path=path).record(usage)
    restored = TokenLedger(path=path)
    assert restored.last.brain == brain
    assert restored.totals.output_tokens == 17


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), "unknown"])
def test_unusable_usage_does_not_book_a_zero_turn(bad):
    ledger = TokenLedger()
    ledger.record(normalize_usage({"input_tokens": bad}))
    assert ledger.totals.prompts == 0
