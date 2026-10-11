"""Per-prompt token accounting: normalization, ledger, and rendering."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.token_meter import (  # noqa: E402
    TokenLedger,
    estimate_tokens,
    format_footer,
    format_history,
    format_status_block,
    human,
    normalize_usage,
    subtract_usage,
)

CLAUDE_USAGE = {
    "input_tokens": 1240,
    "output_tokens": 830,
    "cache_read_input_tokens": 12400,
    "cache_creation_input_tokens": 200,
}
CODEX_USAGE = {
    "inputTokens": 900,
    "cachedInputTokens": 4000,
    "outputTokens": 610,
    "reasoningOutputTokens": 480,
    "totalTokens": 5510,
}


def test_normalizes_the_anthropic_shape():
    usage = normalize_usage(CLAUDE_USAGE, brain="claude", model="opus")
    assert usage is not None
    assert usage.input_tokens == 1240
    assert usage.output_tokens == 830
    assert usage.cache_read_tokens == 12400
    assert usage.cache_write_tokens == 200
    # Anthropic reports no total, so one is derived from every counter.
    assert usage.total_tokens == 1240 + 830 + 12400 + 200
    # Cache reads are not billed as fresh input and stay out of "in".
    assert usage.billed_input == 1440


def test_normalizes_the_codex_shape_and_keeps_its_own_total():
    usage = normalize_usage(CODEX_USAGE, brain="codex", model="gpt-5-codex")
    assert usage is not None
    assert usage.input_tokens == 900
    assert usage.cache_read_tokens == 4000
    assert usage.reasoning_tokens == 480
    assert usage.total_tokens == 5510


def test_empty_or_useless_payloads_are_skipped_not_booked_as_zero():
    assert normalize_usage(None) is None
    assert normalize_usage({}) is None
    assert normalize_usage({"input_tokens": 0, "output_tokens": 0}) is None


def test_cumulative_counters_difference_into_a_single_turn():
    delta = subtract_usage(
        {"inputTokens": 900, "outputTokens": 610, "totalTokens": 1510},
        {"inputTokens": 400, "outputTokens": 210, "totalTokens": 610},
    )
    assert delta["input_tokens"] == 500
    assert delta["output_tokens"] == 400
    assert delta["total_tokens"] == 900


def test_a_reset_thread_reports_the_current_value_not_a_negative_delta():
    delta = subtract_usage({"inputTokens": 50}, {"inputTokens": 900})
    assert delta["input_tokens"] == 50


def test_ledger_totals_sum_every_recorded_prompt():
    ledger = TokenLedger()
    ledger.record(normalize_usage(CLAUDE_USAGE, brain="claude", cost_usd=0.01))
    ledger.record(normalize_usage(CODEX_USAGE, brain="codex", cost_usd=0.02))
    totals = ledger.totals
    assert totals.prompts == 2
    assert totals.input_tokens == 1240 + 900
    assert totals.output_tokens == 830 + 610
    assert round(totals.cost_usd, 4) == 0.03
    assert ledger.totals_for_brain("codex").prompts == 1


def test_ledger_is_bounded_and_keeps_the_newest_entries():
    ledger = TokenLedger(max_entries=3)
    for index in range(10):
        ledger.record(
            normalize_usage({"input_tokens": index + 1, "output_tokens": 1})
        )
    assert len(ledger.entries) == 3
    assert ledger.last.input_tokens == 10


def test_ledger_round_trips_through_disk(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = TokenLedger(path=path)
    ledger.record(normalize_usage(CLAUDE_USAGE, brain="claude", prompt="hello there"))
    reloaded = TokenLedger(path=path)
    assert reloaded.totals.prompts == 1
    assert reloaded.last.brain == "claude"
    assert reloaded.last.prompt_preview == "hello there"


def test_a_corrupt_ledger_file_loads_as_empty_instead_of_raising(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json", encoding="utf-8")
    assert TokenLedger(path=path).totals.prompts == 0


def test_clear_empties_the_ledger_on_disk(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = TokenLedger(path=path)
    ledger.record(normalize_usage(CLAUDE_USAGE))
    ledger.clear()
    assert TokenLedger(path=path).totals.prompts == 0


def test_footer_reports_in_out_and_total():
    usage = normalize_usage(CLAUDE_USAGE, brain="claude", cost_usd=0.0312)
    ledger = TokenLedger()
    ledger.record(usage)
    footer = format_footer(usage, ledger.totals)
    assert "in 1,440" in footer
    assert "out 830" in footer
    assert "total 14.7k" in footer
    assert "cached 12.4k" in footer
    assert "$0.0312" in footer
    assert "1 prompt" in footer


def test_status_block_is_absent_until_something_is_recorded():
    assert format_status_block(TokenLedger()) is None


def test_history_names_every_prompt_and_the_session_total():
    ledger = TokenLedger()
    ledger.record(normalize_usage(CLAUDE_USAGE, brain="claude", prompt="first ask"))
    ledger.record(normalize_usage(CODEX_USAGE, brain="codex", prompt="second ask"))
    text = format_history(ledger)
    assert "first ask" in text
    assert "second ask" in text
    assert "[claude]" in text and "[codex]" in text
    assert "Session:" in text


def test_history_is_helpful_when_nothing_has_been_recorded():
    assert "No prompts recorded yet" in format_history(TokenLedger())


def test_estimates_scale_with_length_and_never_return_zero_for_text():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") >= 1
    assert estimate_tokens("word " * 1000) > estimate_tokens("word " * 10)


def test_human_switches_units_at_sensible_thresholds():
    assert human(940) == "940"
    assert human(41_900) == "41.9k"
    assert human(1_240_000) == "1.24M"


def test_a_cut_short_turn_is_labelled_in_every_view():
    stopped = normalize_usage(
        {"input_tokens": 900, "output_tokens": 120},
        brain="claude",
        prompt="long job",
        outcome="stopped",
    )
    ledger = TokenLedger()
    ledger.record(stopped)
    assert "stopped mid-turn" in format_footer(stopped, ledger.totals)
    assert "stopped" in format_status_block(ledger)
    history = format_history(ledger)
    assert "stopped" in history
    assert "1 of the recorded prompts were cut short" in history


def test_a_failed_turn_is_labelled_separately_from_a_stopped_one():
    failed = normalize_usage(
        {"input_tokens": 120, "output_tokens": 0}, outcome="error"
    )
    assert "turn failed" in format_footer(failed)


def test_cut_short_turns_still_count_toward_the_session_total():
    ledger = TokenLedger()
    ledger.record(normalize_usage({"input_tokens": 100, "output_tokens": 10}))
    ledger.record(
        normalize_usage({"input_tokens": 900, "output_tokens": 120}, outcome="stopped")
    )
    assert ledger.totals.prompts == 2
    assert ledger.totals.input_tokens == 1000


def test_outcome_survives_a_round_trip_through_disk(tmp_path):
    path = tmp_path / "ledger.json"
    TokenLedger(path=path).record(
        normalize_usage({"input_tokens": 5, "output_tokens": 1}, outcome="stopped")
    )
    assert TokenLedger(path=path).last.outcome == "stopped"


def test_a_normal_turn_carries_no_label():
    ok = normalize_usage({"input_tokens": 10, "output_tokens": 5})
    assert ok.outcome == "ok"
    assert "stopped" not in format_footer(ok)
    assert "failed" not in format_footer(ok)


def test_human_never_prints_a_thousand_k():
    assert human(999_949) == "999.9k"
    assert human(999_950) == "1.00M"
    assert human(999_999) == "1.00M"
    assert human(9_999) == "9,999"
    assert human(10_000) == "10k"
    assert human(None) == "?"


def test_ledger_with_hand_edited_garbage_loads_and_still_renders(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"entries": [
        {"input_tokens": "lots", "output_tokens": 5, "at": "yesterday",
         "cost_usd": "free", "brain": 7, "outcome": None, "prompt_preview": ["x"]},
        {"input_tokens": 3, "at": 1e30, "cost_usd": float("nan"), "outcome": "stopped"},
        {"input_tokens": 2, "cost_usd": -1, "unknown_field": True},
        "not a row",
    ]}), encoding="utf-8")
    ledger = TokenLedger(path=path)
    assert len(ledger.entries) == 3
    first, second, third = ledger.entries
    assert (first.input_tokens, first.output_tokens, first.at) == (0, 5, 0.0)
    assert first.cost_usd is None and first.brain == "" and first.outcome == "ok"
    assert second.outcome == "stopped" and second.at == 0.0 and second.cost_usd is None
    assert third.cost_usd is None
    # None of the display paths may raise on restored data.
    assert "Last 3 prompts" in format_history(ledger)
    assert format_status_block(ledger)
    assert format_footer(ledger.last, ledger.totals)


def test_ledger_accepts_a_bare_list_and_ignores_other_shapes(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps([{"input_tokens": 4, "output_tokens": 1}]), encoding="utf-8")
    assert TokenLedger(path=path).totals.prompts == 1
    path.write_text(json.dumps({"entries": "nope"}), encoding="utf-8")
    assert TokenLedger(path=path).totals.prompts == 0
    path.write_text(json.dumps(42), encoding="utf-8")
    assert TokenLedger(path=path).totals.prompts == 0


def test_totals_by_brain_and_cost_rounding():
    ledger = TokenLedger()
    ledger.record(normalize_usage({"input_tokens": 10, "output_tokens": 1},
                                  brain="claude", cost_usd=0.1))
    ledger.record(normalize_usage({"input_tokens": 20, "output_tokens": 2},
                                  brain="codex"))
    ledger.record(normalize_usage({"input_tokens": 30, "output_tokens": 3},
                                  brain="claude", cost_usd=0.2))
    assert ledger.totals_for_brain("claude").prompts == 2
    assert ledger.totals_for_brain("claude").cost_usd == 0.3
    assert ledger.totals_for_brain("codex").cost_usd is None
    assert ledger.totals.billed_input == 60


def test_recent_handles_non_positive_limits_and_oversized_ones():
    ledger = TokenLedger()
    for n in range(1, 4):
        ledger.record(normalize_usage({"input_tokens": n, "output_tokens": 1}))
    assert ledger.recent(0) == [] and ledger.recent(-3) == []
    assert len(ledger.recent(99)) == 3
    assert ledger.recent(2)[0].input_tokens == 2


def test_normalize_ignores_nan_negative_and_non_numeric_counters():
    usage = normalize_usage({"input_tokens": float("nan"), "output_tokens": "7",
                             "cache_read_input_tokens": -4})
    assert usage.input_tokens == 0 and usage.output_tokens == 7
    assert usage.cache_read_tokens == 0
    assert usage.total_tokens == 7
    assert normalize_usage("not a dict") is None
    assert normalize_usage({}) is None


def test_subtract_usage_handles_missing_baselines():
    assert subtract_usage({"inputTokens": 5, "outputTokens": 2}, None)["input_tokens"] == 5
    assert subtract_usage({"inputTokens": 5}, {"inputTokens": 9})["input_tokens"] == 5


def test_prompt_preview_collapses_whitespace_and_truncates():
    usage = normalize_usage({"output_tokens": 1}, prompt="a\n\n  b   " + "z" * 100)
    assert usage.prompt_preview.startswith("a b zzz")
    assert len(usage.prompt_preview) == 60 and usage.prompt_preview.endswith("…")
