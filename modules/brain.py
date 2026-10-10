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
import hashlib
import json
import logging
import uuid
from pathlib import Path
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
    """Shared approval logic with one-time and exact-action session grants.

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
        self.grants: dict[str, dict[str, Any]] = {}
        self._permission_scopes: dict[str, dict[str, Any]] = {}
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
            if normalized == "session":
                scope = self._permission_scopes.get(request_id)
                if scope is not None:
                    self.grants[scope["id"]] = dict(scope)
                    log.info("Granted exact action %s for this session", scope["id"])
                else:
                    normalized = "deny"
            fut.set_result(normalized in ("allow", "session"))
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
        *,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Ask the owner to approve an action; return True=allow, False=deny.

        *candidates* are scanned against ``OFFLIMITS_FRAGMENTS`` first; a match
        is auto-denied without bothering the phone. Otherwise a Telegram
        prompt is sent and we await Allow once, Deny, or an exact-action grant.
        Grants expire on session reset, revocation, or process restart. Context
        binds grants to provider workspace and complete native tool arguments.
        """
        screened = list(candidates)
        if context and context.get("paths"):
            try:
                workspace = Path(context["workspace"]).resolve()
                for target in context["paths"]:
                    path = Path(target).expanduser()
                    resolved = (
                        path.resolve() if path.is_absolute()
                        else (workspace / path).resolve()
                    )
                    screened.append(str(resolved))
            except (OSError, RuntimeError, ValueError, TypeError, KeyError):
                self.telegram.send(self.owner, "⛔ Could not resolve action paths.")
                return False
        frag = self.offlimits_match(screened)
        if frag is not None:
            self.telegram.send(
                self.owner, f"⛔ Auto-denied {title} (off-limits: {frag})"
            )
            log.warning("Auto-denied off-limits action %s (fragment %s)", title, frag)
            return False

        if self.auto_approve:
            log.info("Auto-approved %s (auto_approve on; not off-limits)", title)
            return True

        identity = json.dumps(
            [title, detail, screened, context or {}],
            sort_keys=True, ensure_ascii=False, default=str,
        )
        grant_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        if grant_id in self.grants:
            log.info("Allowed %s through exact-action grant %s", title, grant_id)
            return True

        request_id = uuid.uuid4().hex[:8]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self.pending[request_id] = (loop, fut)
        self._permission_scopes[request_id] = {
            "id": grant_id, "title": title, "detail": detail,
            "candidates": list(candidates), "context": context or {},
        }

        header = f"\U0001f510 Permission request: {title}"
        if detail:
            header += f"\n\n{detail[:1500]}"
        header += (
            "\n\nAllow once, deny, or allow this exact action again for this "
            "session. Changed arguments or workspace require a new approval. "
            "Use /permissions to inspect or revoke grants."
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
            self._permission_scopes.pop(request_id, None)
            cancel = getattr(self.telegram, "cancel_permission", None)
            if cancel is not None:
                cancel(self.owner, request_id)

    def revoke_grants(self, grant_id: str | None = None) -> int:
        """Revoke one exact grant or all grants, including legacy auto mode."""
        # Invalidate immediately, before a queued Telegram callback can resolve.
        # The future belongs to the brain loop; only that loop may settle it.
        for request_id, scope in list(self._permission_scopes.items()):
            if grant_id is not None and scope["id"] != grant_id:
                continue
            item = self.pending.pop(request_id, None)
            if item is not None:
                loop, future = item
                def deny_pending(future=future):
                    if not future.done():
                        future.set_result(False)
                if not loop.is_closed():
                    loop.call_soon_threadsafe(deny_pending)
            cancel = getattr(self.telegram, "cancel_permission", None)
            if cancel is not None:
                cancel(self.owner, request_id)
        if grant_id is not None:
            return int(self.grants.pop(grant_id, None) is not None)
        count = len(self.grants) + int(self.auto_approve)
        self.grants.clear()
        self.auto_approve = False
        return count

    def format_grants(self) -> str:
        lines = ["Permission grants (current session)"]
        if self.auto_approve:
            lines.append("Legacy configured global auto-approval is active.")
        if not self.grants:
            lines.append("No exact-action grants.")
        for grant_id, grant in self.grants.items():
            lines.append(f"{grant_id}\n{grant['title']}: {grant['detail'][:200]}")
        lines.append("/permissions revoke <id|all>")
        return "\n\n".join(lines)

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
    compaction_status: str = "idle"

    async def compact(self, *, timeout: float = 120) -> str | None:
        """Compact natively; return an error, or None after verified completion."""
        self.last_turn_usage = None
        self.last_turn_cost_usd = None
        return "Native compaction is unavailable for this brain."

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
