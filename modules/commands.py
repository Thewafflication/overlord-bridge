"""Telegram command help and status formatting for the Overlord bridge."""

from __future__ import annotations

import datetime
from typing import Any

from modules.token_meter import TokenLedger, format_status_block, human
from modules.version import display_version


HELP_TEXT = """Overlord commands

/help — list available commands
/status — show the active brain, model, effort, usage and tokens
/status all — show every brain side by side
/tokens [n] — per-prompt token history (default 10)
/quote <text> — estimate the input tokens a prompt would cost
/model [name] — show or switch the active brain's model
/effort [level] — show or switch the reasoning effort level
/questions — show the pending question and its ID
/reply <id> <answer> — answer a specific pending question
/cancelquestion <id> — cancel a specific pending question
/permissions [revoke <id|all>] — inspect or revoke exact-action grants
/context — show retained context and checkpoint recovery status
/compact — compact the idle conversation with the provider's native mechanism
/stop — stop the active AI turn
/steer <message> — stop the active turn and replace it with new guidance
/brain — show or switch the active brain
/new — start a clean conversation"""

VALID_BRAINS = ("claude", "codex")


def set_env_value(path: Any, key: str, value: str) -> None:
    """Update one dotenv setting while preserving unrelated configuration."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip()
        if name == key:
            lines[index] = f"{key}={value}"
            replaced = True
    if not replaced:
        lines.append(f"{key}={value}")
    rendered = newline.join(lines) + newline
    path.write_text(rendered, encoding="utf-8")


def _friendly_local_time(
    value: datetime.datetime,
    *,
    now: datetime.datetime | None = None,
) -> str:
    """Render an aware timestamp in the machine's local timezone."""
    local = value.astimezone()
    local_now = (now or datetime.datetime.now().astimezone()).astimezone()
    day_delta = (local.date() - local_now.date()).days
    if day_delta == 0:
        day = "Today"
    elif day_delta == 1:
        day = "Tomorrow"
    elif day_delta == -1:
        day = "Yesterday"
    else:
        day = local.strftime("%a, %b %d").replace(" 0", " ")
    clock = local.strftime("%I:%M %p").lstrip("0")
    zone = local.tzname() or local.strftime("%z")
    return f"{day} at {clock} {zone}".rstrip()


def _format_reset(value: Any) -> str | None:
    reset: datetime.datetime
    if isinstance(value, (int, float)):
        try:
            reset = datetime.datetime.fromtimestamp(
                value, tz=datetime.timezone.utc
            ).astimezone()
        except (OSError, OverflowError, ValueError):
            return None
        return _friendly_local_time(reset)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            reset = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if reset.tzinfo is None:
            reset = reset.astimezone()
        return _friendly_local_time(reset)
    return None


def _format_window(label: str, window: Any) -> str:
    if not isinstance(window, dict):
        return f"{label}: unavailable"
    used = window.get("used")
    left = window.get("gas")
    if isinstance(used, (int, float)) and isinstance(left, (int, float)):
        text = f"{label}: {used:g}% used, {left:g}% left"
    elif isinstance(used, (int, float)):
        text = f"{label}: {used:g}% used"
    else:
        return f"{label}: unavailable"
    reset = _format_reset(window.get("resets_at"))
    return f"{text} · resets {reset}" if reset else text


def _format_tokens(tokens: Any) -> str | None:
    if not isinstance(tokens, dict):
        return None
    total = tokens.get("totalTokens")
    latest = tokens.get("lastTotalTokens")
    context = tokens.get("modelContextWindow")
    if not isinstance(total, int):
        return None
    lines = [f"Thread tokens: {total:,} cumulative"]
    if isinstance(latest, int) and isinstance(context, int) and context > 0:
        percent = min(100, round(latest * 100 / context))
        lines.append(
            f"Latest turn: {latest:,} / {context:,} token window ({percent}%)"
        )
    elif isinstance(context, int) and context > 0:
        lines.append(f"Model context window: {context:,} tokens")
    return "\n".join(lines)


def format_status(status: dict[str, Any]) -> str:
    """Render a compact, Telegram-friendly brain status message."""
    brain = str(status.get("brain") or "unknown")
    model = str(status.get("model") or "default")
    lines = [
        f"🤖 Overlord status · {display_version()}",
        f"Brain: {brain}",
        f"Model: {model}",
    ]

    turn_state = status.get("turn_state")
    if turn_state:
        lines.append(f"Turn: {turn_state}")

    effort = status.get("effort")
    lines.append(f"Effort: {effort or 'default'}")

    provider = status.get("model_provider")
    if provider:
        lines.append(f"Provider: {provider}")
    session_id = status.get("session_id")
    if session_id == "saved":
        # A standby brain: the pin exists on disk but nothing is holding it.
        lines.append("Session: saved, not loaded")
    else:
        lines.append(f"Session: {'active' if session_id else 'not started'}")

    ledger = status.get("ledger")
    if isinstance(ledger, TokenLedger):
        block = format_status_block(ledger)
        if block:
            lines.append(block)

    token_line = _format_tokens(status.get("tokens"))
    if token_line:
        lines.append(token_line)

    usage = status.get("usage")
    if isinstance(usage, dict):
        plan = usage.get("plan_type")
        if plan:
            lines.append(f"Plan: {plan}")
        lines.append(_format_window("5-hour", usage.get("session")))
        lines.append(_format_window("Weekly", usage.get("weekly")))
    else:
        lines.append("Usage: unavailable from this brain")

    note = status.get("usage_note")
    if note:
        lines.append(str(note))
    checked = status.get("checked_at")
    if isinstance(checked, (int, float)):
        lines.append(f"Checked: {_age(checked)}")
    return "\n".join(lines)


def _age(timestamp: float, *, now: float | None = None) -> str:
    """Render how long ago a status reading was taken.

    Shown on every ``/status`` so a stale number is visibly stale rather than
    quietly wrong — the old behaviour sent the cache and only *then* refreshed,
    which made every reading exactly one command out of date with nothing on
    screen to say so.
    """
    current = now if now is not None else datetime.datetime.now().timestamp()
    seconds = max(0, int(current - timestamp))
    if seconds < 5:
        return "just now"
    if seconds < 90:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m ago"
    return f"{minutes // 60}h ago"


def format_brain_card(name: str, status: dict[str, Any], active_brain: str) -> str:
    """One brain's status as a labelled card, header line replaced.

    Shared by the Tk console's side-by-side cards and by ``/status all`` so the
    two never drift: there is exactly one place that decides what a brain's
    status looks like, and it is :func:`format_status`.
    """
    role = "ACTIVE" if name == active_brain else "STANDBY"
    complete = {"brain": name, **status}
    # Drop format_status's own header and its "Brain:" line; the card heading
    # already says which brain this is and whether it is the live one.
    details = format_status(complete).splitlines()[2:]
    return "\n".join([f"{name.upper()}  •  {role}", *details])


def format_status_all(statuses: dict[str, dict[str, Any]], active_brain: str) -> str:
    """``/status all``: every configured brain, active one first.

    Only the active brain can be read live — asking a standby Codex for its rate
    limits would mean spawning its app-server — so the others are rendered from
    their last cached usage and their configured settings, and labelled as such.
    """
    ordered = sorted(statuses, key=lambda name: (name != active_brain, name))
    blocks = [f"🤖 Overlord status · {display_version()}"]
    for name in ordered:
        blocks.append(format_brain_card(name, statuses.get(name) or {}, active_brain))
    blocks.append(
        "Standby brains are shown from their last cached reading; switch with "
        "/brain <name> for live numbers."
    )
    return "\n\n".join(blocks)


def format_quote(
    *,
    prompt_tokens: int,
    source: str,
    context_tokens: int | None = None,
    context_source: str = "estimate",
    model: str = "",
    brain: str = "",
) -> str:
    """Render ``/quote``: what a proposed prompt would cost as input."""
    label = "exact" if source == "exact" else "estimated"
    lines = [
        "📐 Prompt quote",
        f"Prompt alone: {human(prompt_tokens)} input tokens ({label})",
    ]
    if context_tokens is not None:
        total = prompt_tokens + context_tokens
        lines.append(
            f"With pending context: ~{human(total)} "
            f"(+{human(context_tokens)} of carried-over conversation)"
        )
    else:
        lines.append(
            "No extra context is queued, so the turn sends roughly this plus the "
            "session's own history, which stays on the provider's side."
        )
    footer = f"{brain or 'brain'} · {model or 'default'}"
    if label == "estimated":
        footer += " · local estimate, ±10% is normal"
    lines.append(footer)
    return "\n".join(lines)
