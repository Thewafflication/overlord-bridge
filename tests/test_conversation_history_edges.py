"""Bounds, markers, and routing context of the shared conversation history."""

import pytest

from modules.conversation_history import SharedConversationHistory, add_handoff_to_turn


def test_blank_messages_are_not_recorded_but_their_counterpart_is():
    history = SharedConversationHistory()
    history.append_exchange("   ", "assistant only")
    history.append_exchange("user only", "\n\n")
    handoff = history.handoff_for("claude")
    assert handoff.entry_count == 2
    assert handoff.text == "Assistant: assistant only\n\nUser: user only"
    assert handoff.upto == 2


def test_a_brain_with_nothing_unseen_gets_no_handoff():
    history = SharedConversationHistory()
    assert history.handoff_for("claude") is None
    history.append_exchange("q", "a")
    history.mark_seen("claude")
    assert history.handoff_for("claude") is None
    assert history.handoff_for("codex").entry_count == 2  # an unseen brain gets it all


def test_oversized_messages_are_cut_in_the_middle_with_a_marker():
    history = SharedConversationHistory(max_handoff_chars=1_000)
    history.append_exchange("head-" + "x" * 9_000 + "-tail", "ok")
    entry = history._entries[0]
    assert len(entry.text) <= 2_000
    assert entry.text.startswith("head-") and entry.text.endswith("-tail")
    assert "\n[truncated]\n" in entry.text


def test_storage_is_bounded_but_never_drops_below_one_exchange():
    history = SharedConversationHistory(max_handoff_chars=1_000)
    for n in range(20):
        history.append_exchange(f"question {n} " + "q" * 1_500, f"answer {n} " + "a" * 1_500)
    stored = sum(len(entry.text) for entry in history._entries)
    assert stored <= 4_000 + 2_000  # the storage cap, plus at most one oversized entry
    assert len(history._entries) >= 2
    assert history._entries[-1].text.startswith("answer 19")
    history.append_exchange("huge " + "z" * 5_000, "huge " + "z" * 5_000)
    assert len(history._entries) >= 2


def test_entry_count_is_capped_at_512():
    history = SharedConversationHistory(max_handoff_chars=1_000_000)
    for n in range(400):
        history.append_exchange(f"q{n}", f"a{n}")
    assert len(history._entries) == 512
    assert history._entries[-1].text == "a399"


def test_handoff_keeps_the_newest_messages_and_trims_the_oldest_that_fit():
    history = SharedConversationHistory(max_handoff_chars=1_000)
    history.append_exchange("A" * 600, "B" * 600)
    history.append_exchange("newest question", "newest answer")
    handoff = history.handoff_for("codex")
    assert handoff.text.endswith("Assistant: newest answer")
    assert "User: newest question" in handoff.text
    assert len(handoff.text) <= 1_000
    assert handoff.entry_count >= 3
    assert handoff.upto == 4


@pytest.mark.parametrize("bad", [-1, 99, True, 1.5, "2"])
def test_seen_markers_must_point_inside_the_conversation(bad):
    history = SharedConversationHistory()
    history.append_exchange("q", "a")
    with pytest.raises(ValueError):
        history.mark_seen("claude", bad)


def test_seen_marker_can_be_set_to_an_earlier_message():
    history = SharedConversationHistory()
    history.append_exchange("q1", "a1")
    history.append_exchange("q2", "a2")
    history.mark_seen("claude", 2)
    assert history.handoff_for("claude").text == "User: q2\n\nAssistant: a2"


def test_routing_context_is_recent_bounded_and_does_not_advance_markers():
    history = SharedConversationHistory(max_handoff_chars=1_000_000)
    for n in range(10):
        history.append_exchange(f"q{n}", f"a{n}")
    context = history.routing_context()
    assert context.count("User:") + context.count("Assistant:") == 8
    assert context.endswith("Assistant: a9") and "q0" not in context
    assert history.handoff_for("claude").entry_count == 20  # nothing marked seen
    history.append_exchange("w" * 5_000, "z" * 5_000)
    assert len(history.routing_context()) == 6_000


def test_clear_forgets_everything_including_sequence_numbers():
    history = SharedConversationHistory()
    history.append_exchange("q", "a")
    history.mark_seen("claude")
    history.clear()
    assert history.handoff_for("claude") is None
    history.append_exchange("fresh", "start")
    assert history.handoff_for("claude").upto == 2
    assert history.status().startswith("Retained conversation: 2 messages")


def test_status_reports_size_limits_and_persistence_state(tmp_path):
    history = SharedConversationHistory(max_handoff_chars=5_000)
    history.append_exchange("hello", "world")
    status = history.status()
    assert "2 messages, 10 characters" in status
    assert "Handoff limit: 5,000 characters" in status
    assert "Durable checkpoint: disabled" in status
    persisted = SharedConversationHistory(path=tmp_path / "c.json")
    assert "Durable checkpoint: enabled" in persisted.status()
    assert persisted.checkpoint() is True
    assert SharedConversationHistory().checkpoint() is False


def test_unwritable_checkpoint_location_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory is needed", encoding="utf-8")
    history = SharedConversationHistory(path=blocker / "sub" / "c.json")
    history.append_exchange("q", "a")  # must not raise
    assert history.checkpoint() is False
    assert "Context save failed" in history.status()


def test_handoff_prompt_puts_the_current_message_last():
    history = SharedConversationHistory()
    history.append_exchange("prior", "reply")
    prompt = add_handoff_to_turn(history.handoff_for("codex"), "now do this")
    assert prompt.index("--- BEGIN PRIOR CONVERSATION ---") < prompt.index("User: prior")
    assert prompt.index("--- END PRIOR CONVERSATION ---") < prompt.index("now do this")
    assert prompt.endswith("now do this")
