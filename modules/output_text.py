"""Explicit summaries and expandable details for user-facing output."""

import html
import re


OUTPUT_INSTRUCTIONS = (
    "Write user-facing replies in plain language. Lead with the outcome or current "
    "status, then explain what the user needs to know. Explain failures by their cause "
    "and next step. Put verbose command output and diagnostic logs in fenced blocks "
    "labelled log so Telegram can collapse them. Keep findings, decisions, instructions "
    "and requested code outside log blocks. Avoid raw tool envelopes or provider metadata "
    "in the main answer. Before related tool calls, briefly explain what you are "
    "investigating or changing and why, naming the relevant files or commands. "
    "Keep these progress notes concise and distinguish plans from completed work."
)


def telegram_blocks(text: str):
    """Yield (plain text, expandable) without trusting model-authored HTML."""
    offset = 0
    for match in re.finditer(r"(?m)^```(?:log|output)[ \t]*\n(.*?)^```[ \t]*(?:\n|$)", text, re.S):
        if match.start() > offset:
            yield text[offset:match.start()], False
        yield match.group(1).rstrip(), True
        offset = match.end()
    if offset < len(text):
        yield text[offset:], False


def expandable_html(text: str) -> str:
    return "<blockquote expandable>" + html.escape(text, quote=False) + "</blockquote>"


def activity_summary(line: str) -> str:
    """Translate the bridge's mechanical log envelope, retaining its message."""
    command = re.search(r"COMMAND (.+?) (started|completed|failed|denied) \| cwd=(.*?) \| (.*)", line)
    if command:
        engine, phase, folder, detail = command.groups()
        labels = {"started": "Running", "completed": "Finished", "failed": "Failed", "denied": "Blocked"}
        result = re.search(r" \| exit=(-?\d+)$", detail)
        if result:
            detail = detail[:result.start()]
            if result.group(1) != "0":
                labels[phase] = f"Failed (exit {result.group(1)})"
        return f"{labels[phase]}: {detail} · {engine}"[:300]
    message = re.split(r"\s(?:INFO|WARNING|ERROR|DEBUG)\s+", line, maxsplit=1)[-1]
    return message.strip()[:300]


def worker_action(tool: str, arguments: dict) -> str:
    tool = {"run": "run_command", "bash": "run_command", "shell": "run_command",
            "write": "write_file"}.get(tool, tool)
    if tool == "read_file":
        return f"Read {arguments.get('path', '(unspecified file)')}"
    if tool == "write_file":
        return f"Write {arguments.get('path', '(unspecified file)')}"
    if tool == "run_python":
        return f"Run Python: {arguments.get('code', '(unspecified code)')}"
    if tool == "run_command":
        return f"Run {arguments.get('command') or arguments.get('cmd') or '(unspecified command)'}"
    if tool == "list_files":
        return "List project files"
    return f"Use tool {tool}"
