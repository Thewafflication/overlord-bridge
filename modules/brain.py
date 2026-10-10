"""Brain abstraction for the Overlord bridge.

The bridge's main loop talks to a *brain* through this interface and never needs
to know whether the brain is Claude (the Agent SDK) or Codex (the App Server).
A brain owns one persistent conversation and exposes an async lifecycle:

    await brain.connect(resume=...)        # start / resume the conversation
    async for chunk in brain.query(text):  # stream assistant text back
        ...
    await brain.reset()                    # /new -> fresh conversation
    await brain.disconnect()               # clean teardown

The per-tool approval round-trip (route to Telegram, await a tap, time out into
a deny) and the ``OFFLIMITS_FRAGMENTS`` backstop are deliberately *not*
Claude-specific: both brains drive them through the same :class:`PermissionGate`,
so the security floor is identical regardless of which brain is active.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import uuid
from typing import Any, AsyncIterator

from modules.telegram_handler import TelegramHandler

log = logging.getLogger("overlord.brain")

# Hard backstop: path fragments that must never be touched, even if a brain
# somehow reaches the approval hook for them. For Claude the real enforcement
# lives in ~/.claude/settings.json deny rules; for Codex it's the sandbox +
# AGENTS.md. This gate is defense in depth for *both*.
OFFLIMITS_FRAGMENTS = (
    "/.ssh",
    "/.gnupg",
    "/.1password",
    "/.netrc",
    "/.smbcredentials",
    "/.aws",
    "/.config/google-chrome",
    "/.mozilla",
    "id_rsa",
    "id_ed25519",
)


class PermissionGate:
    """Shared approval logic with one-time and runtime-wide Telegram choices.

    A brain calls :meth:`request` with a human-readable description of what the
    agent wants to do plus a list of strings to scan for off-limits fragments
    (paths, commands). The gate returns ``True`` to allow and ``False`` to deny.
    Both brains map ``False`` onto their own "deny" decision and ``True`` onto
    "allow", so the policy itself is defined exactly once, here.
    """

    def __init__(
        self,
        telegram: TelegramHandler,
        owner: int,
        timeout: int,
        auto_approve: bool = False,
    ) -> None:
        self.telegram = telegram
        self.owner = owner
        self.timeout = timeout
        # When True, skip the Telegram permission round-trip and auto-allow —
        # BUT only after the off-limits pre-screen below. "Trust me, stop asking"
        # must never extend to reading secrets, so the hard floor still applies.
        self.auto_approve = auto_approve
        # request_id -> (loop, future); the Telegram thread resolves the future
        # created on this loop when a button is tapped.
        self.pending: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Future]] = {}
        self.choice_pending: dict[
            str, tuple[asyncio.AbstractEventLoop, asyncio.Future]
        ] = {}

    def on_permission_response(self, request_id: str, decision: str | bool) -> None:
        """Resolve a Telegram permission decision on the requesting event loop."""
        item = self.pending.get(request_id)
        if item is None:
            return
        loop, fut = item
        def resolve():
            if self.pending.pop(request_id, None) is None or fut.done():
                return
            normalized = (
                "allow"
                if decision is True
                else "deny"
                if decision is False
                else decision
            )
            if normalized == "always":
                self.auto_approve = True
                log.warning(
                    "Operator enabled runtime auto-approval; off-limits checks remain active"
                )
            fut.set_result(normalized in ("allow", "always"))
        if not loop.is_closed():
            loop.call_soon_threadsafe(resolve)

    def on_choice_response(self, request_id: str, answer: str) -> None:
        """Resolve a model-authored Telegram question."""
        item = self.choice_pending.get(request_id)
        if item is None:
            return
        loop, fut = item
        def resolve():
            if self.choice_pending.pop(request_id, None) is not None:
                if not fut.done():
                    fut.set_result(answer)
        if not loop.is_closed():
            loop.call_soon_threadsafe(resolve)

    @staticmethod
    def offlimits_match(candidates: list[str]) -> str | None:
        """Return the first off-limits fragment found in *candidates*, or None."""
        for s in candidates:
            if not isinstance(s, str):
                continue
            normalized = s.replace("\\", "/").lower()
            for frag in OFFLIMITS_FRAGMENTS:
                if frag.lower() in normalized:
                    return frag
        return None

    async def request(
        self,
        title: str,
        detail: str,
        candidates: list[str],
    ) -> bool:
        """Ask the owner to approve an action; return True=allow, False=deny.

        *candidates* are scanned against ``OFFLIMITS_FRAGMENTS`` first; a match
        is auto-denied without bothering the phone. Otherwise a Telegram
        prompt is sent and we await Allow once, Deny, or Always allow. The last
        choice enables auto-approval only for this process lifetime; off-limits
        checks still run before it.
        """
        frag = self.offlimits_match(candidates)
        if frag is not None:
            self.telegram.send(
                self.owner, f"⛔ Auto-denied {title} (off-limits: {frag})"
            )
            log.warning("Auto-denied off-limits action %s (fragment %s)", title, frag)
            return False

        if self.auto_approve:
            log.info("Auto-approved %s (auto_approve on; not off-limits)", title)
            return True

        request_id = uuid.uuid4().hex[:8]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self.pending[request_id] = (loop, fut)

        header = f"\U0001f510 Permission request: {title}"
        if detail:
            header += f"\n\n{detail[:1500]}"
        header += (
            "\n\nAllow this? “Always allow” applies until Overlord restarts; "
            "off-limits paths remain denied."
        )
        try:
            self.telegram.ask_permission(self.owner, header, request_id)
            return await asyncio.wait_for(fut, timeout=self.timeout)
        except asyncio.TimeoutError:
            self.pending.pop(request_id, None)
            self.telegram.send(
                self.owner, f"⏱ Permission timed out for {title} — denied."
            )
            return False
        finally:
            self.pending.pop(request_id, None)

    async def choose(
        self,
        prompt: str,
        options: list[tuple[str, str]],
    ) -> str | None:
        """Ask the owner a model-authored question over Telegram."""
        request_id = uuid.uuid4().hex[:8]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self.choice_pending[request_id] = (loop, fut)
        try:
            self.telegram.ask_choice(self.owner, prompt, request_id, options)
            answer = await asyncio.wait_for(fut, timeout=self.timeout)
            if not isinstance(answer, str):
                return None
            return answer.strip() or None
        except asyncio.TimeoutError:
            self.telegram.send(self.owner, "⏱ Question timed out — no answer sent.")
            return None
        finally:
            self.choice_pending.pop(request_id, None)
            self.telegram.cancel_choice(self.owner, request_id)


class Brain(abc.ABC):
    """A swappable conversational engine driving one persistent conversation.

    Implementations own their transport (Claude Agent SDK, Codex App Server) and
    their session persistence, but route every approval through the shared
    :class:`PermissionGate` so guardrails are brain-independent.
    """

    name: str = "brain"

    # Per-turn accounting, refreshed by ``query()`` as each turn closes and read
    # by the bridge right after the stream ends. Kept as a plain attribute (not
    # a yielded value) because ``query()`` yields *text to relay* — threading a
    # usage dict through that stream would force every consumer to type-check
    # each chunk. ``None`` means "this turn reported nothing", which is normal
    # for paths that hand the turn to another process (Claude's shared job).
    last_turn_usage: dict[str, Any] | None = None
    last_turn_cost_usd: float | None = None
    # "ok" | "error" — how the ENGINE ended the turn. Interruption is the
    # bridge's own knowledge (it did the interrupting), so "stopped" is applied
    # there rather than here.
    last_turn_outcome: str = "ok"

    # Whether ``set_effort`` does anything for this brain.
    supports_effort: bool = False

    @abc.abstractmethod
    async def connect(self, resume: str | None = None) -> None:
        """Start (or resume) the conversation. *resume* is a persisted session id."""

    @abc.abstractmethod
    def query(self, text: str) -> AsyncIterator[str]:
        """Send a user turn and yield assistant text chunks to relay to Telegram.

        This is an async generator. Implementations should yield each meaningful
        chunk of assistant text as it arrives. Approval prompts are handled
        internally via the :class:`PermissionGate` and are *not* yielded.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def reset(self) -> None:
        """Wipe persisted session state and start a fresh conversation (/new)."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Tear down the transport cleanly."""

    # Convenience: brains may override to surface a current session id (mostly
    # for logging / debugging). Not required by the main loop.
    @property
    def session_id(self) -> str | None:  # pragma: no cover - trivial default
        return None

    async def record_event(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """Append a bridge-owned event to the conversation, if supported.

        This is intentionally not a normal user turn: callers use it for
        out-of-band bridge status such as worker completions. Brains that cannot
        safely append context should return ``False`` and rely on external audit
        storage instead.
        """
        return False

    async def record_visible_event(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """Start a visible bridge-owned status turn, if safely supported.

        This is for opt-in UI visibility of out-of-band status. Implementations
        must keep it distinct from a normal user turn and must not approve tool
        use while the status turn is running.
        """
        return False

    async def interrupt_active_turn(self) -> bool:
        """Interrupt the currently active turn, if the brain supports it."""
        return False

    async def status(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Return model/session metadata and usage exposed by this brain.

        *force_refresh* asks the brain to bypass any usage cache it keeps, at
        the cost of a network round-trip. The bridge sets it for an operator's
        explicit ``/status`` and leaves it off for background refreshes.
        """
        return {
            "brain": self.name,
            "model": getattr(self, "model", None) or "default",
            "session_id": self.session_id,
            "usage": None,
        }

    async def set_model(self, model: str) -> str | None:
        """Switch the model used for subsequent turns.

        Returns ``None`` on success, or a human-readable reason it could not be
        applied. Brains apply the change to the *next* turn rather than the one
        in flight, so a switch never truncates a running answer.
        """
        return f"{self.name} cannot change its model at runtime."

    async def set_effort(self, effort: str) -> str | None:
        """Switch the reasoning-effort level, same contract as :meth:`set_model`."""
        return f"{self.name} does not expose a reasoning-effort setting."

    async def count_input_tokens(self, text: str) -> tuple[int | None, str]:
        """Count the input tokens *text* would cost, without spending a turn.

        Returns ``(count, source)`` where *source* names how it was measured
        (``"exact"`` from the provider, ``"estimate"`` from a local heuristic)
        so callers can label the number honestly. ``(None, reason)`` means the
        brain could not count it at all.
        """
        return None, "no token counter available for this brain"


def collect_candidates(tool_input: dict[str, Any], path_keys: tuple[str, ...]) -> list[str]:
    """Pull path-like / command strings out of a tool-input dict for scanning."""
    out: list[str] = []
    for key in path_keys:
        val = tool_input.get(key)
        if isinstance(val, str):
            out.append(val)
    cmd = tool_input.get("command")
    if isinstance(cmd, str):
        out.append(cmd)
    return out
