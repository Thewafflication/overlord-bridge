import asyncio

from modules.brain import PermissionGate


class FakeTelegram:
    def __init__(self):
        self.prompts = []
        self.messages = []

    def ask_permission(self, owner, text, request_id):
        self.prompts.append((owner, text, request_id))

    def send(self, owner, text):
        self.messages.append((owner, text))

    def ask_choice(self, owner, prompt, request_id, options):
        self.prompts.append((owner, prompt, request_id, options))

    def cancel_choice(self, owner, request_id):
        return None


def test_always_allow_applies_for_runtime_but_not_offlimits():
    async def scenario():
        telegram = FakeTelegram()
        gate = PermissionGate(telegram, owner=42, timeout=1)

        first = asyncio.create_task(
            gate.request("Bash", "git status", ["git status"])
        )
        await asyncio.sleep(0)
        request_id = telegram.prompts[0][2]
        gate.on_permission_response(request_id, "always")

        assert await first is True
        assert gate.auto_approve is True
        assert await gate.request("Bash", "git diff", ["git diff"]) is True
        assert len(telegram.prompts) == 1

        denied = await gate.request(
            "Read", "private key", ["C:/Users/me/.ssh/id_ed25519"]
        )
        assert denied is False
        assert "Auto-denied" in telegram.messages[-1][1]

    asyncio.run(scenario())


def test_model_choice_can_be_answered_from_telegram():
    async def scenario():
        telegram = FakeTelegram()
        gate = PermissionGate(telegram, owner=42, timeout=1)
        waiting = asyncio.create_task(
            gate.choose("Which approach?", [("A", "Fast"), ("B", "Safe")])
        )
        await asyncio.sleep(0)
        request_id = telegram.prompts[0][2]
        gate.on_choice_response(request_id, "B")
        assert await waiting == "B"

    asyncio.run(scenario())
