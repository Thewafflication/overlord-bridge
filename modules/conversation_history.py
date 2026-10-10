"""Bounded, brain-neutral context handoffs for runtime brain switching."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import tempfile


log = logging.getLogger("overlord.context")


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

    def __init__(
        self, max_handoff_chars: int = 12_000, *, path: Path | None = None,
        workspace: str = "",
    ) -> None:
        self.max_handoff_chars = max(1_000, max_handoff_chars)
        self._entries: list[_Entry] = []
        self._seen: dict[str, int] = {}
        self._sequence = 0
        self.path = path
        self.workspace = workspace
        self.persistence_note: str | None = None
        self._load()

    def _decode(self, path: Path) -> dict:
        if path.stat().st_size > self.max_handoff_chars * 16 + 128_000:
            raise ValueError("checkpoint exceeds storage limit")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != 1:
            raise ValueError("unsupported checkpoint schema")
        if data.get("workspace") != self.workspace:
            raise ValueError("checkpoint belongs to another workspace")
        sequence = data.get("sequence")
        if type(sequence) is not int or sequence < 0:
            raise ValueError("invalid sequence")
        entries = data.get("entries")
        seen = data.get("seen")
        if (
            not isinstance(entries, list) or len(entries) > 512
            or not isinstance(seen, dict)
        ):
            raise ValueError("invalid checkpoint collections")
        prior = 0
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("invalid entry")
            number = entry.get("sequence")
            if type(number) is not int or not prior < number <= sequence:
                raise ValueError("invalid entry sequence")
            if entry.get("role") not in {"User", "Assistant"}:
                raise ValueError("invalid conversation role")
            if not isinstance(entry.get("text"), str):
                raise ValueError("invalid conversation text")
            prior = number
        if any(
            not isinstance(name, str) or type(number) is not int
            or not 0 <= number <= sequence for name, number in seen.items()
        ):
            raise ValueError("invalid seen markers")
        return data

    def _load(self) -> None:
        if self.path is None:
            return
        failures = []
        for candidate in (self.path, self.path.with_suffix(".previous")):
            try:
                data = self._decode(candidate)
            except FileNotFoundError:
                continue
            except (OSError, ValueError, TypeError) as exc:
                failures.append(str(exc))
                continue
            self._entries = [
                _Entry(entry["sequence"], entry["role"], entry["text"])
                for entry in data["entries"]
            ]
            self._seen = data["seen"]
            self._sequence = data["sequence"]
            if candidate != self.path:
                self.persistence_note = "Recovered previous context checkpoint."
            return
        if failures:
            self.persistence_note = "Context checkpoint unavailable: " + "; ".join(failures)
            log.warning(self.persistence_note)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _save(self, *, reset: bool = False) -> None:
        if self.path is None:
            return
        data = {
            "schema": 1, "workspace": self.workspace,
            "sequence": self._sequence, "seen": self._seen,
            "entries": [
                {"sequence": e.sequence, "role": e.role, "text": e.text}
                for e in self._entries
            ],
        }
        text = json.dumps(data, ensure_ascii=False)
        backup = self.path.with_suffix(".previous")
        try:
            if reset:
                # Do not recover a previous conversation after an explicit /new.
                self._atomic_write(backup, text)
            elif self.path.exists():
                try:
                    old = self._decode(self.path)
                except (OSError, ValueError, TypeError):
                    old = None
                if old is not None:
                    self._atomic_write(backup, json.dumps(old, ensure_ascii=False))
            self._atomic_write(self.path, text)
        except OSError as exc:
            self.persistence_note = f"Context save failed: {exc}"
            log.warning(self.persistence_note)

    def status(self) -> str:
        text = (
            f"Retained conversation: {len(self._entries)} messages, "
            f"{sum(len(entry.text) for entry in self._entries):,} characters\n"
            f"Sequence: {self._sequence}\n"
            f"Handoff limit: {self.max_handoff_chars:,} characters\n"
            f"Durable checkpoint: {'enabled' if self.path else 'disabled'}"
        )
        if self.persistence_note:
            text += f"\n{self.persistence_note}"
        return text

    def append_exchange(self, user_text: str, assistant_text: str) -> None:
        for role, text in (("User", user_text), ("Assistant", assistant_text)):
            clean = text.strip()
            if not clean:
                continue
            self._sequence += 1
            limit = self.max_handoff_chars * 2
            if len(clean) > limit:
                marker = "\n[truncated]\n"
                fragment = (limit - len(marker)) // 2
                clean = clean[:fragment] + marker + clean[-fragment:]
            self._entries.append(_Entry(self._sequence, role, clean))

        # Retain several handoff windows while keeping memory bounded.
        storage_limit = self.max_handoff_chars * 4
        stored = sum(len(entry.text) for entry in self._entries)
        while len(self._entries) > 2 and (
            stored > storage_limit or len(self._entries) > 512
        ):
            stored -= len(self._entries.pop(0).text)
        self._save()

    def mark_seen(self, brain_name: str, upto: int | None = None) -> None:
        if upto is not None and (type(upto) is not int or not 0 <= upto <= self._sequence):
            raise ValueError("seen marker is outside the conversation")
        self._seen[brain_name] = self._sequence if upto is None else upto
        self._save()

    def clear(self) -> None:
        self._entries.clear()
        self._seen.clear()
        self._sequence = 0
        self.persistence_note = None
        self._save(reset=True)

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
