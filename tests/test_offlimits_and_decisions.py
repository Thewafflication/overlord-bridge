"""PermissionGate off-limits screening and decision outcomes."""

import asyncio

import pytest

from modules.brain import PermissionGate, collect_candidates


class Telegram:
    def __init__(self):
        self.prompts = []
        self.messages = []
        self.cancelled = []

    def ask_permission(self, owner, text, request_id):
        self.prompts.append((text, request_id))

    def send(self, owner, text):
        self.messages.append(text)

    def cancel_permission(self, owner, request_id):
        self.cancelled.append(request_id)

    def ask_choice(self, owner, prompt, request_id, options):
        self.prompts.append((prompt, request_id))

    def cancel_choice(self, owner, request_id):
        self.cancelled.append(request_id)


class RecordingAudit:
    def __init__(self, ok=True):
        self.ok = ok
        self.records = []

    def record(self, **kwargs):
        self.records.append(kwargs)
        return self.ok


def run(coro):
    return asyncio.run(coro)


# -------------------------------------------------------------- screening
@pytest.mark.parametrize(
    "candidate",
    [
        "~/.ssh/config",
        "C:\\Users\\me\\.aws\\credentials",
        "cat .ssh/config",
        "cd .gnupg && ls",
        "export CREDS=.aws/credentials",
        "ls '.config/google-chrome/Default'",
        "(.mozilla/firefox)",
        "type notes;.netrc",
        ".1password/vault",
        "scp host:keys/id_rsa .",
        "ID_ED25519",
        ".smbcredentials",
    ],
)
def test_secret_locations_are_caught_with_or_without_a_leading_slash(candidate):
    assert PermissionGate.offlimits_match([candidate]) is not None


@pytest.mark.parametrize(
    "candidate",
    [
        "git status",
        "/home/me/ssh/notes.txt",
        "src/foo.ssh/readme",
        "sshd_config.md",
        "docs/aws-guide.md",
        "mozilla.txt",
        "",
    ],
)
def test_ordinary_text_is_not_mistaken_for_a_secret_location(candidate):
    assert PermissionGate.offlimits_match([candidate]) is None


def test_non_string_candidates_are_skipped_not_fatal():
    assert PermissionGate.offlimits_match([None, 7, ["x"], "~/.ssh/id_rsa"]) == "/.ssh"
    assert PermissionGate.offlimits_match([]) is None


def test_collect_candidates_gathers_paths_and_the_command():
    tool_input = {"file_path": "a.py", "path": 5, "command": "ls -la", "other": "ignored"}
    assert collect_candidates(tool_input, ("file_path", "path", "directory")) == [
        "a.py", "ls -la",
    ]


# ------------------------------------------------------------ decisions
def test_auto_approve_still_denies_secrets_and_never_prompts():
    async def scenario():
        telegram = Telegram()
        gate = PermissionGate(telegram, 42, 1, auto_approve=True)
        assert await gate.request("Bash", "ls", ["ls"]) is True
        assert await gate.request("Bash", "cat .ssh/id", ["cat .ssh/id"]) is False
        assert telegram.prompts == []
        assert "off-limits" in telegram.messages[-1]

    run(scenario())


def test_relative_paths_in_context_are_resolved_against_the_workspace(tmp_path):
    async def scenario():
        telegram = Telegram()
        gate = PermissionGate(telegram, 42, 1)
        workspace = tmp_path / ".ssh"
        workspace.mkdir()
        denied = await gate.request(
            "Write", "edit", ["notes.txt"],
            context={"workspace": str(workspace), "paths": ["notes.txt"]},
        )
        assert denied is False
        assert telegram.prompts == []

    run(scenario())


def test_unresolvable_context_paths_fail_closed():
    async def scenario():
        telegram = Telegram()
        gate = PermissionGate(telegram, 42, 1)
        denied = await gate.request(
            "Write", "edit", [], context={"paths": ["a.py"]}  # no workspace key
        )
        assert denied is False
        assert "Could not resolve" in telegram.messages[-1]

    run(scenario())


def test_unanswered_request_times_out_into_a_denial_and_cleans_up():
    async def scenario():
        telegram = Telegram()
        gate = PermissionGate(telegram, 42, 0.05)
        assert await gate.request("Bash", "make", ["make"]) is False
        assert "timed out" in telegram.messages[-1]
        assert gate.pending == {} and gate._permission_scopes == {}
        assert telegram.cancelled  # the buttons were invalidated

    run(scenario())


def test_explicit_deny_and_one_time_allow_do_not_create_grants():
    async def scenario():
        telegram = Telegram()
        gate = PermissionGate(telegram, 42, 1)
        for decision, expected in (("deny", False), ("allow", True)):
            task = asyncio.create_task(gate.request("Bash", "make", ["make"]))
            await asyncio.sleep(0)
            gate.on_permission_response(telegram.prompts[-1][1], decision)
            assert await task is expected
        assert gate.grants == {}

    run(scenario())


def test_legacy_boolean_decisions_and_unknown_decisions():
    async def scenario():
        telegram = Telegram()
        gate = PermissionGate(telegram, 42, 1)
        for decision, expected in ((True, True), (False, False), ("whatever", False)):
            task = asyncio.create_task(gate.request("Bash", "make", ["make"]))
            await asyncio.sleep(0)
            gate.on_permission_response(telegram.prompts[-1][1], decision)
            assert await task is expected

    run(scenario())


def test_response_for_an_unknown_request_is_ignored():
    gate = PermissionGate(Telegram(), 42, 1)
    gate.on_permission_response("nope", "allow")
    gate.on_choice_response("nope", "answer")


def test_cancelling_a_pending_request_is_audited_and_propagates():
    async def scenario():
        audit = RecordingAudit()
        gate = PermissionGate(Telegram(), 42, 5, audit=audit)
        task = asyncio.create_task(gate.request("Bash", "make", ["make"]))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert audit.records[-1]["source"] == "cancelled"
        assert gate.pending == {}

    run(scenario())


def test_failed_audit_write_denies_an_approved_action_and_drops_the_grant():
    async def scenario():
        telegram = Telegram()
        gate = PermissionGate(telegram, 42, 1, audit=RecordingAudit(ok=False))
        task = asyncio.create_task(gate.request("Bash", "make", ["make"]))
        await asyncio.sleep(0)
        gate.on_permission_response(telegram.prompts[-1][1], "session")
        assert await task is False
        assert gate.grants == {}
        assert gate.audit_ok is False
        assert any("audit" in m.lower() for m in telegram.messages)

    run(scenario())


def test_audit_that_raises_is_treated_as_unavailable():
    class Exploding:
        def record(self, **kwargs):
            raise OSError("disk full")

    async def scenario():
        gate = PermissionGate(Telegram(), 42, 1, auto_approve=True, audit=Exploding())
        assert await gate.request("Bash", "ls", ["ls"]) is False

    run(scenario())


def test_revoking_everything_also_turns_off_global_auto_approval():
    gate = PermissionGate(Telegram(), 42, 1, auto_approve=True)
    gate.grants["abc"] = {"title": "Bash", "detail": "ls", "id": "abc"}
    assert gate.revoke_grants() == 2
    assert gate.auto_approve is False and gate.grants == {}
    assert gate.revoke_grants("abc") == 0


def test_format_grants_lists_grants_and_audit_state():
    audit = RecordingAudit()
    gate = PermissionGate(Telegram(), 42, 1, audit=audit)
    assert "not yet used" in gate.format_grants()
    gate.grants["abc123"] = {"title": "Bash", "detail": "git status", "id": "abc123"}
    gate.audit_ok = True
    text = gate.format_grants()
    assert "abc123" in text and "git status" in text and "healthy" in text
    gate.audit_ok = False
    assert "unavailable" in gate.format_grants()


# ---------------------------------------------------------------- choices
def test_choose_times_out_to_none_and_blank_answers_are_none():
    async def scenario():
        telegram = Telegram()
        gate = PermissionGate(telegram, 42, 0.05)
        assert await gate.choose("Pick", [("a", "")]) is None
        assert "timed out" in telegram.messages[-1]
        gate.timeout = 1
        task = asyncio.create_task(gate.choose("Pick", [("a", "")]))
        await asyncio.sleep(0)
        gate.on_choice_response(telegram.prompts[-1][1], "   ")
        assert await task is None
        task = asyncio.create_task(gate.choose("Pick", [("a", "")]))
        await asyncio.sleep(0)
        gate.on_choice_response(telegram.prompts[-1][1], "  a  ")
        assert await task == "a"
        assert gate.choice_pending == {}

    run(scenario())
