"""Per-prompt token accounting for the Overlord bridge.

Both brains report usage, but in different shapes:

  * Claude's Agent SDK closes every turn with a ``ResultMessage`` whose
    ``usage`` dict uses Anthropic's API names (``input_tokens``,
    ``output_tokens``, ``cache_read_input_tokens``,
    ``cache_creation_input_tokens``) plus a ``total_cost_usd``.
  * Codex's app-server pushes ``thread/tokenUsage/updated`` notifications
    carrying camelCase counters (``inputTokens``, ``cachedInputTokens``,
    ``outputTokens``, ``reasoningOutputTokens``, ``totalTokens``) split into a
    cumulative ``total`` and a per-turn ``last``.

:func:`normalize_usage` flattens either shape into a :class:`TurnUsage`, and
:class:`TokenLedger` keeps a bounded, disk-backed history so ``/tokens`` and
``/status`` survive a bridge restart. Nothing here ever raises into the turn
path: accounting must never be the reason a reply fails to send.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("overlord.tokens")

# Keep the on-disk ledger small enough to load instantly on every restart.
DEFAULT_MAX_ENTRIES = 200

# Key aliases, in preference order, for each counter we track. Covers the
# Anthropic snake_case shape and the Codex camelCase shape in one table.
_ALIASES: dict[str, tuple[str, ...]] = {
    "input_tokens": ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens"),
    "output_tokens": (
        "output_tokens",
        "outputTokens",
        "completion_tokens",
        "completionTokens",
    ),
    "cache_read_tokens": (
        "cache_read_input_tokens",
        "cacheReadInputTokens",
        "cached_input_tokens",
        "cachedInputTokens",
    ),
    "cache_write_tokens": (
        "cache_creation_input_tokens",
        "cacheCreationInputTokens",
        "cache_write_tokens",
        "cacheWriteTokens",
    ),
    "reasoning_tokens": (
        "reasoning_output_tokens",
        "reasoningOutputTokens",
        "reasoning_tokens",
        "reasoningTokens",
    ),
    "total_tokens": ("total_tokens", "totalTokens"),
}


def _as_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _pick(raw: dict[str, Any], field_name: str) -> int:
    for key in _ALIASES[field_name]:
        if key in raw:
            return _as_int(raw[key])
    return 0


@dataclass
class TurnUsage:
    """One prompt's accounting: what went in, what came out, what it cost."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None
    brain: str = ""
    model: str = ""
    at: float = 0.0
    prompt_preview: str = ""

    @property
    def billed_input(self) -> int:
        """Fresh input plus cache writes — the part that is not a cache hit.

        Cache *reads* are billed at a fraction of the input rate and are
        reported separately so a long resumed session doesn't look like it is
        re-sending its whole history at full price every turn.
        """
        return self.input_tokens + self.cache_write_tokens

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_usage(
    raw: Any,
    *,
    brain: str = "",
    model: str = "",
    cost_usd: float | None = None,
    at: float | None = None,
    prompt: str = "",
) -> TurnUsage | None:
    """Flatten a brain's usage payload into a :class:`TurnUsage`, or None.

    Returns None when *raw* carries no usable counters, so callers can simply
    skip the footer rather than reporting a row of zeros.
    """
    if not isinstance(raw, dict):
        return None
    usage = TurnUsage(
        input_tokens=_pick(raw, "input_tokens"),
        output_tokens=_pick(raw, "output_tokens"),
        cache_read_tokens=_pick(raw, "cache_read_tokens"),
        cache_write_tokens=_pick(raw, "cache_write_tokens"),
        reasoning_tokens=_pick(raw, "reasoning_tokens"),
        total_tokens=_pick(raw, "total_tokens"),
        cost_usd=cost_usd,
        brain=brain,
        model=model,
        at=at if at is not None else datetime.datetime.now().timestamp(),
        prompt_preview=_preview(prompt),
    )
    if usage.total_tokens <= 0:
        # Codex reports a total; Anthropic does not. Derive one, counting cache
        # reads so "total" means "tokens this turn touched", matching what the
        # provider dashboards show.
        usage.total_tokens = (
            usage.input_tokens
            + usage.output_tokens
            + usage.cache_read_tokens
            + usage.cache_write_tokens
        )
    if usage.total_tokens <= 0 and usage.output_tokens <= 0:
        return None
    return usage


def subtract_usage(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, int]:
    """Difference two cumulative counter dicts into a per-turn delta.

    Used for brains that only publish running totals. A negative delta means
    the thread was reset underneath us, so the current value is returned as-is.
    """
    delta: dict[str, int] = {}
    for name in _ALIASES:
        now = _pick(current, name)
        before = _pick(previous, name) if isinstance(previous, dict) else 0
        value = now - before
        delta[name] = now if value < 0 else value
    return delta


def _preview(text: str, limit: int = 60) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


# ------------------------------------------------------------------ estimation
def estimate_tokens(text: str) -> int:
    """Approximate the token count of *text* without calling a provider.

    Prefers ``tiktoken`` when it happens to be installed; otherwise blends a
    character-density and a word-count model and takes the larger. Both models
    lean slightly high on code and punctuation, which is the right bias for a
    quote: better to over-reserve than to promise a prompt fits when it does not.
    """
    if not text:
        return 0
    try:  # pragma: no cover - depends on an optional dependency
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:  # noqa: BLE001 - any failure falls through to the heuristic
        pass
    words = len(text.split())
    return max(1, int(math.ceil(max(len(text) / 3.8, words * 1.3))))


# ---------------------------------------------------------------- presentation
def human(count: int | float | None) -> str:
    """Render a token count compactly: 940, 41.9k, 1.24M."""
    if count is None:
        return "?"
    number = float(count)
    if abs(number) < 10_000:
        return f"{int(round(number)):,}"
    if abs(number) < 1_000_000:
        return f"{number / 1_000:.1f}k".replace(".0k", "k")
    return f"{number / 1_000_000:.2f}M"


def _cost(value: float | None) -> str | None:
    if value is None:
        return None
    return f"${value:,.4f}" if value < 1 else f"${value:,.2f}"


def format_footer(usage: TurnUsage, totals: "LedgerTotals | None" = None) -> str:
    """One compact line to append after a reply."""
    bits = [
        f"in {human(usage.billed_input)}",
        f"out {human(usage.output_tokens)}",
        f"total {human(usage.total_tokens)}",
    ]
    if usage.cache_read_tokens:
        bits.append(f"cached {human(usage.cache_read_tokens)}")
    cost = _cost(usage.cost_usd)
    if cost:
        bits.append(cost)
    line = "🧮 " + " · ".join(bits)
    if totals is not None and totals.prompts > 0:
        line += (
            f"\nSession: {human(totals.total_tokens)} over "
            f"{totals.prompts} prompt{'s' if totals.prompts != 1 else ''}"
        )
        session_cost = _cost(totals.cost_usd)
        if session_cost:
            line += f" · {session_cost}"
    return line


def format_status_block(ledger: "TokenLedger") -> str | None:
    """The token section of ``/status``: last prompt plus session totals."""
    totals = ledger.totals
    if totals.prompts == 0:
        return None
    lines: list[str] = []
    last = ledger.last
    if last is not None:
        parts = [
            f"in {human(last.billed_input)}",
            f"out {human(last.output_tokens)}",
            f"total {human(last.total_tokens)}",
        ]
        if last.cache_read_tokens:
            parts.append(f"cached {human(last.cache_read_tokens)}")
        lines.append("Last prompt: " + " · ".join(parts))
    session = (
        f"Session tokens: {human(totals.total_tokens)} over {totals.prompts} "
        f"prompt{'s' if totals.prompts != 1 else ''} "
        f"(in {human(totals.billed_input)} · out {human(totals.output_tokens)})"
    )
    cost = _cost(totals.cost_usd)
    if cost:
        session += f" · {cost}"
    lines.append(session)
    return "\n".join(lines)


def format_history(ledger: "TokenLedger", limit: int = 10) -> str:
    """The ``/tokens`` reply: the most recent prompts, newest last."""
    entries = ledger.recent(limit)
    if not entries:
        return (
            "🧮 No prompts recorded yet.\n"
            "Token accounting starts with the next message you send."
        )
    lines = [f"🧮 Last {len(entries)} prompt{'s' if len(entries) != 1 else ''}"]
    for index, usage in enumerate(entries, start=1):
        when = datetime.datetime.fromtimestamp(usage.at).strftime("%H:%M")
        head = (
            f"{index}. {when} [{usage.brain or '?'}] "
            f"in {human(usage.billed_input)} · out {human(usage.output_tokens)} · "
            f"total {human(usage.total_tokens)}"
        )
        cost = _cost(usage.cost_usd)
        if cost:
            head += f" · {cost}"
        lines.append(head)
        if usage.prompt_preview:
            lines.append(f"   “{usage.prompt_preview}”")
    totals = ledger.totals
    footer = (
        f"Session: {human(totals.total_tokens)} total · "
        f"in {human(totals.billed_input)} · out {human(totals.output_tokens)}"
    )
    if totals.cache_read_tokens:
        footer += f" · cached {human(totals.cache_read_tokens)}"
    session_cost = _cost(totals.cost_usd)
    if session_cost:
        footer += f" · {session_cost}"
    lines.append("")
    lines.append(footer)
    return "\n".join(lines)


# --------------------------------------------------------------------- ledger
@dataclass
class LedgerTotals:
    prompts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None

    @property
    def billed_input(self) -> int:
        return self.input_tokens + self.cache_write_tokens


@dataclass
class TokenLedger:
    """A bounded, disk-backed history of per-prompt usage."""

    path: Path | None = None
    max_entries: int = DEFAULT_MAX_ENTRIES
    entries: list[TurnUsage] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.path is not None:
            self.load()

    # -- state ---------------------------------------------------------------
    @property
    def last(self) -> TurnUsage | None:
        return self.entries[-1] if self.entries else None

    def recent(self, limit: int = 10) -> list[TurnUsage]:
        if limit <= 0:
            return []
        return self.entries[-limit:]

    @property
    def totals(self) -> LedgerTotals:
        return self._totals_of(self.entries)

    def totals_for_brain(self, brain: str) -> LedgerTotals:
        return self._totals_of([e for e in self.entries if e.brain == brain])

    @staticmethod
    def _totals_of(entries: Iterable[TurnUsage]) -> LedgerTotals:
        totals = LedgerTotals()
        cost = 0.0
        has_cost = False
        for usage in entries:
            totals.prompts += 1
            totals.input_tokens += usage.input_tokens
            totals.output_tokens += usage.output_tokens
            totals.cache_read_tokens += usage.cache_read_tokens
            totals.cache_write_tokens += usage.cache_write_tokens
            totals.total_tokens += usage.total_tokens
            if usage.cost_usd is not None:
                cost += usage.cost_usd
                has_cost = True
        totals.cost_usd = round(cost, 6) if has_cost else None
        return totals

    # -- mutation ------------------------------------------------------------
    def record(self, usage: TurnUsage | None) -> TurnUsage | None:
        if usage is None:
            return None
        self.entries.append(usage)
        if len(self.entries) > self.max_entries:
            del self.entries[: len(self.entries) - self.max_entries]
        self.save()
        return usage

    def clear(self) -> None:
        self.entries.clear()
        self.save()

    # -- persistence ---------------------------------------------------------
    def load(self) -> None:
        if self.path is None:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        rows = raw.get("entries") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return
        known = {f for f in TurnUsage().as_dict()}
        restored: list[TurnUsage] = []
        for row in rows[-self.max_entries :]:
            if not isinstance(row, dict):
                continue
            try:
                restored.append(TurnUsage(**{k: v for k, v in row.items() if k in known}))
            except (TypeError, ValueError):
                continue
        self.entries = restored

    def save(self) -> None:
        if self.path is None:
            return
        payload = {
            "version": 1,
            "entries": [usage.as_dict() for usage in self.entries],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            log.debug("Could not persist the token ledger: %s", exc)
