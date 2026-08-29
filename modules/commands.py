"""Telegram command help and status formatting for the Overlord bridge."""

from __future__ import annotations

import datetime
from typing import Any


HELP_TEXT = """Overlord commands

/help — list available commands
/status — show the active brain, model, and usage
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


def _format_reset(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        try:
            reset = datetime.datetime.fromtimestamp(value).astimezone()
        except (OSError, OverflowError, ValueError):
            return None
        return reset.strftime("%b %d, %I:%M %p").replace(" 0", " ")
    if isinstance(value, str) and value.strip():
        return value.strip()
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
