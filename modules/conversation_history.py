"""Bounded, brain-neutral context handoffs for runtime brain switching."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Handoff:
    """A snapshot of unseen conversation context for one brain."""

    text: str
    upto: int
    entry_count: int


@dataclass(frozen=True)
class _Entry:
    sequence: int
    role: str
    text: str


class SharedConversationHistory:
    """Track recent Telegram turns and what each brain has already seen."""

    def __init__(self, max_handoff_chars: int = 12_000) -> None:
        self.max_handoff_chars = max(1_000, max_handoff_chars)
        self._entries: list[_Entry] = []
        self._seen: dict[str, int] = {}
        self._sequence = 0

    def append_exchange(self, user_text: str, assistant_text: str) -> None:
        for role, text in (("User", user_text), ("Assistant", assistant_text)):
            clean = text.strip()
            if not clean:
                continue
            self._sequence += 1
            self._entries.append(_Entry(self._sequence, role, clean))

        # Retain several handoff windows while keeping memory bounded.
        storage_limit = self.max_handoff_chars * 4
        stored = sum(len(entry.text) for entry in self._entries)
        while len(self._entries) > 2 and stored > storage_limit:
            stored -= len(self._entries.pop(0).text)

    def mark_seen(self, brain_name: str, upto: int | None = None) -> None:
        self._seen[brain_name] = self._sequence if upto is None else upto

    def clear(self) -> None:
        self._entries.clear()
        self._seen.clear()
        self._sequence = 0

    def handoff_for(self, brain_name: str) -> Handoff | None:
        unseen = [
            entry
            for entry in self._entries
            if entry.sequence > self._seen.get(brain_name, 0)
        ]
        if not unseen:
            return None

        selected: list[str] = []
        used = 0
        for entry in reversed(unseen):
            rendered = f"{entry.role}: {entry.text}"
            remaining = self.max_handoff_chars - used
            if remaining <= 0:
                break
            if len(rendered) > remaining:
                rendered = rendered[-remaining:]
            selected.append(rendered)
            used += len(rendered) + 2
        selected.reverse()
        return Handoff("\n\n".join(selected), unseen[-1].sequence, len(selected))


def add_handoff_to_turn(handoff: Handoff, user_text: str) -> str:
    """Attach prior context to the first real user turn after a switch."""
    return (
        "The bridge has switched AI engines. The following is a bounded transcript "
        "of messages this engine has not seen. Use it only for conversational "
        "continuity; do not summarize or acknowledge the handoff unless asked.\n\n"
        "--- BEGIN PRIOR CONVERSATION ---\n"
        f"{handoff.text}\n"
        "--- END PRIOR CONVERSATION ---\n\n"
        "Answer this current user message normally:\n"
        f"{user_text}"
    )
