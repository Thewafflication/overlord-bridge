import asyncio

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from modules.brain import PermissionGate
from modules.claude_brain import ClaudeBrain
from modules.codex_brain import CodexBrain


def test_long_reviews_retain_every_answer_without_truncating_action_prompt():
    sent = []
    class Telegram:
        def send(self, owner, text):
            sent.append(text)
    gate = PermissionGate(Telegram(), 42, 1)
    prompts = []
    async def choose(prompt, options):
        prompts.append(prompt)
        return "Submit answers"
    gate.choose = choose
    answers = {"first": "A" * 4000, "last": "LAST ANSWER"}
    questions = [{"key": key, "prompt": key, "options": []} for key in answers]
    assert asyncio.run(gate.review_answers(questions, answers)) == answers
    assert "LAST ANSWER" in sent[0]
    assert len(prompts[0]) < 3500


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("cancel", [False, True])
def test_full_question_set_review_edits_or_cancels(tmp_path, provider, cancel):
    gate = PermissionGate(None, 42, 1)
    prompts = []
    replies = iter(["A", "B", "Edit an answer", "Question 2", "C",
                    "Cancel answers" if cancel else "Submit answers"])
    async def choose(prompt, options):
        prompts.append((prompt, options))
        return next(replies)
    gate.choose = choose
    cls = ClaudeBrain if provider == "claude" else CodexBrain
    brain = cls(gate=gate, cwd=str(tmp_path), model="test", session_file=tmp_path / "session")
    questions = [{"id": "first", "question": "First?", "options": []},
                 {"id": "second", "question": "Second?", "options": []}]
    if provider == "claude":
        result = asyncio.run(brain._answer_user_questions({"questions": questions}))
        if cancel:
            assert isinstance(result, PermissionResultDeny)
        else:
            assert isinstance(result, PermissionResultAllow)
            assert result.updated_input["answers"] == {"First?": "A", "Second?": "C"}
    else:
        result = asyncio.run(brain._request_user_input({"questions": questions}))
        assert result == {"answers": {} if cancel else {
            "first": {"answers": ["A"]}, "second": {"answers": ["C"]}}}
    assert "Question 1 of 2" in prompts[0][0]
    assert "Answer: A" in prompts[2][0] and "Answer: B" in prompts[2][0]
    assert "Answer: C" in prompts[-1][0]


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_cancellation_mid_set_never_returns_partial_answers(tmp_path, provider):
    gate = PermissionGate(None, 42, 1)
    replies = iter(["A", None])
    async def choose(*args):
        return next(replies)
    gate.choose = choose
    cls = ClaudeBrain if provider == "claude" else CodexBrain
    brain = cls(gate=gate, cwd=str(tmp_path), model="test", session_file=tmp_path / "session")
    request = {"questions": [{"id": "a", "question": "First?"},
                             {"id": "b", "question": "Second?"}]}
    if provider == "claude":
        assert isinstance(asyncio.run(brain._answer_user_questions(request)), PermissionResultDeny)
    else:
        assert asyncio.run(brain._request_user_input(request)) == {"answers": {}}


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("questions", [[{}, {"id": "x", "question": "Valid?"}],
    [{"id": "same", "question": "Same?"}] * 2,
    [{"id": str(i), "question": f"Question {i}?"} for i in range(5)]])
def test_invalid_or_oversized_sets_do_not_prompt(tmp_path, provider, questions):
    gate = PermissionGate(None, 42, 1)
    calls = []
    async def choose(*args):
        calls.append(args)
        return "unused"
    gate.choose = choose
    cls = ClaudeBrain if provider == "claude" else CodexBrain
    brain = cls(gate=gate, cwd=str(tmp_path), model="test", session_file=tmp_path / "session")
    request = {"questions": questions}
    if provider == "claude":
        assert isinstance(asyncio.run(brain._answer_user_questions(request)), PermissionResultDeny)
    else:
        assert asyncio.run(brain._request_user_input(request)) == {"answers": {}}
    assert calls == []
