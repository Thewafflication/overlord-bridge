"""Telegram command help and status formatting for the Overlord bridge."""

from __future__ import annotations

import datetime
from typing import Any


HELP_TEXT = """Overlord commands

/help — list available commands
/status — show the active brain, model, and usage
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
    lines = ["🤖 Overlord status", f"Brain: {brain}", f"Model: {model}"]

    turn_state = status.get("turn_state")
    if turn_state:
        lines.append(f"Turn: {turn_state}")

    provider = status.get("model_provider")
    if provider:
        lines.append(f"Provider: {provider}")
    lines.append(f"Session: {'active' if status.get('session_id') else 'not started'}")

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
    return "\n".join(lines)
