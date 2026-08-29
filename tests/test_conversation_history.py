from modules.conversation_history import (
    SharedConversationHistory,
    add_handoff_to_turn,
)


def test_handoff_contains_only_messages_unseen_by_target():
    history = SharedConversationHistory()
    history.append_exchange("first", "answer one")
    history.mark_seen("codex")
    history.append_exchange("second", "answer two")

    handoff = history.handoff_for("codex")

    assert handoff is not None
    assert "first" not in handoff.text
    assert "second" in handoff.text
    assert "answer two" in handoff.text


def test_handoff_is_attached_to_current_turn_with_clear_boundaries():
    history = SharedConversationHistory()
    history.append_exchange("prior question", "prior answer")
    handoff = history.handoff_for("claude")

    prompt = add_handoff_to_turn(handoff, "continue from there")

    assert "BEGIN PRIOR CONVERSATION" in prompt
    assert "User: prior question" in prompt
    assert prompt.endswith("continue from there")


def test_handoff_is_bounded_to_recent_context():
    history = SharedConversationHistory(max_handoff_chars=1_000)
    history.append_exchange("old-" + "x" * 900, "middle-" + "y" * 900)
    history.append_exchange("recent", "latest")

    handoff = history.handoff_for("codex")

    assert handoff is not None
    assert len(handoff.text) <= 1_002
    assert "recent" in handoff.text
    assert "latest" in handoff.text
