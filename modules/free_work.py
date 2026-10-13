"""Let free models work on projects: the ``/work`` command and its guard rails.

The free brain can dispatch project work through chat tools or /work.
Project work runs as a *worker*: the same tool
loop (list/read/write files, run commands inside one project folder, with the
built-in secret/path denial rules) that the local-agent and NVIDIA workers use, but
fed by the free-model pool so it shares the chat's rate limits, cooldowns and
fallback. Because free models are less predictable, writes and commands ask the
operator first by default (exact-action "allow for this session" grants apply).

``/work``                      list projects
``/work <project> <task>``     start a free-model worker in that project
``/work status``               show running free workers
``/work stop [project]``       cancel one (or all) free workers
"""

from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger("overlord.free_work")

APPROVAL_MODES = ("all", "commands", "none")
USAGE = (
    "Usage: /work <project> <task>\n"
    "Also: /work (list projects) · /work status · /work stop [project]"
)
MAX_LISTED = 40


def normalize_mode(value: str | None) -> str:
    mode = (value or "all").strip().lower()
    return mode if mode in APPROVAL_MODES else "all"


def list_projects(roots: list[Path], projects: list[Path] | None = None) -> list[tuple[str, Path, bool]]:
    """(name, path, is_git_repo) for each project folder directly under the roots."""
    found: dict[str, tuple[str, Path, bool]] = {}
    for path in projects or []:
        if path.is_dir():
            found.setdefault(path.name.lower(), (path.name, path, (path / ".git").exists()))
    for root in roots:
        try:
            children = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            continue
        for child in children:
            found.setdefault(child.name.lower(), (child.name, child, (child / ".git").exists()))
    return sorted(found.values(), key=lambda item: item[0].lower())


def resolve_project(name: str, roots: list[Path], projects: list[Path] | None = None) -> Path | None:
    """A project by folder name (case-insensitive) under the roots, or an absolute path."""
    name = name.strip().strip('"').strip("'")
    if not name:
        return None
    candidate = Path(name).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.is_dir() else None
    if any(sep in name for sep in ("/", chr(92))) or name in (".", ".."):
        return None  # a bare project name only; no relative escapes
    for _, path, _ in list_projects(roots, projects):
        if path.name.lower() == name.lower():
            return path
    return None


class FreeWork:
    def __init__(
        self,
        *,
        send: Callable[[int, str], None],
        roots: Callable[[], list[Path]],
        workers: Any,
        gate: Any,
        pool: Callable[[], Awaitable[Any]],
        approval: str = "all",
        patience: float = 120.0,
        projects: Callable[[], list[Path]] | None = None,
    ) -> None:
        self._send, self._roots, self.workers, self.gate = send, roots, workers, gate
        self._pool = pool
        self.approval = normalize_mode(approval)
        self.patience = patience
        self._projects = projects or (lambda: [])

    # ------------------------------------------------------------- commands
    def chat_tools(self) -> list[dict[str, Any]]:
        projects = list_projects(self._roots(), self._projects())
        if not projects:
            return []
        return [{"type": "function", "function": {
            "name": "start_project_work",
            "description": "Start a tool-enabled worker to inspect, review or change a local project. "
                           "Resolve the user's project description to a listed folder. "
                           "For code review, request findings with file/line evidence and no edits. "
                           "Ask for clarification if the project is ambiguous.",
            "parameters": {"type": "object", "properties": {
                "project": {"type": "string", "enum": [name for name, _, _ in projects]},
                "task": {"type": "string"}}, "required": ["project", "task"],
                "additionalProperties": False}}}]

    def execute_chat_tool(self, chat_id: int, call: dict[str, Any]) -> str:
        function = call.get("function", {})
        if function.get("name") != "start_project_work":
            return "Unknown project tool."
        try:
            args = json.loads(function["arguments"])
            project, task = args["project"], args["task"]
            names = [name for name, _, _ in list_projects(self._roots(), self._projects())]
            if project not in names or not isinstance(task, str) or not task.strip():
                return "Invalid project or task; no worker started."
        except (KeyError, TypeError, ValueError):
            return "Invalid project tool arguments; no worker started."
        name = f"Free-{project}"
        if name in self.workers._running:
            return f"{name} is already running."
        self._start(chat_id, project, task.strip())
        return (f"{name} started; results will arrive when the local project review or task finishes."
                if name in self.workers._running else f"{name} could not start.")

    async def handle(self, chat_id: int, text: str) -> None:
        parts = text.strip().split(maxsplit=2)
        sub = parts[1].lower() if len(parts) > 1 else ""
        if sub in ("", "list", "projects"):
            self._send(chat_id, self._project_list())
        elif sub == "status":
            self._send(chat_id, self._status())
        elif sub == "stop":
            self._send(chat_id, self._stop(parts[2].strip() if len(parts) > 2 else ""))
        elif len(parts) < 3 or not parts[2].strip():
            self._send(chat_id, USAGE)
        else:
            self._start(chat_id, parts[1], parts[2].strip())

    def _project_list(self) -> str:
        projects = list_projects(self._roots(), self._projects())
        if not projects:
            return "No project folders found.\n" + USAGE
        names = [("● " if git else "○ ") + name for name, _, git in projects[:MAX_LISTED]]
        more = f"\n…and {len(projects) - MAX_LISTED} more" if len(projects) > MAX_LISTED else ""
        return ("Projects (● git repo):\n" + "\n".join(names) + more
                + "\n\nStart one with /work <project> <task>.")

    def _free_names(self) -> list[str]:
        return [n for n in self.workers._running if n.startswith("Free-")]

    def _status(self) -> str:
        running = self._free_names()
        if not running:
            return "No free-model workers are running."
        return "Running free-model workers:\n" + "\n".join(f"• {n}" for n in running)

    def _stop(self, project: str) -> str:
        running = self.workers._running
        names = [n for n in self._free_names()
                 if not project or n.lower() == f"free-{project}".lower()]
        if not names:
            return f"No free-model worker is running{' for ' + project if project else ''}."
        for name in names:
            running[name].cancel()
        return "Stopping: " + ", ".join(names) + " (it reports when it has stopped)."

    def _start(self, chat_id: int, project: str, task: str) -> None:
        path = resolve_project(project, self._roots(), self._projects())
        if path is None:
            self._send(chat_id, f"Unknown project “{project}”. Send /work to list them.")
            return
        name = f"Free-{path.name}"
        if name in self.workers._running:
            self._send(chat_id, f"{name} is already running. /work stop {path.name} first.")
            return
        self.workers._accept({"name": name, "folder": str(path), "task": task, "brain": "free"})
        if name not in self.workers._running:
            return  # _accept already explained the rejection
        asks = {"all": "writes and commands", "commands": "commands", "none": "nothing"}[self.approval]
        self._send(
            chat_id,
            f"🛠 {name} started in {path}.\nIt asks you before: {asks}. "
            "I'll message you when it finishes (/work status · /work stop).",
        )

    # ------------------------------------------------- worker callbacks
    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        """One assistant turn from the shared pool (waiting out short rate limits)."""
        pool = await self._pool()
        message, spec, _ = await pool.complete(messages, tools, patience=self.patience)
        message["_free_model"] = spec.key
        return message

    async def approve(self, folder: Path, tool: str, request: dict[str, Any]) -> str | None:
        """None to proceed, or the reason the operator (or policy) refused."""
        if self.approval == "none" or (tool == "write_file" and self.approval != "all"):
            return None
        if tool == "run_command":
            command = request["command"]
            title, detail = "Free worker: run command", f"{command}\n(in {folder})"
            candidates, context = [command], {"workspace": str(folder), "request": request}
        else:
            content = request["content"]
            preview = content[:400] + ("…" if len(content) > 400 else "")
            title = "Free worker: write file"
            detail = f"{request['path']} ({len(content)} chars)\n\n{preview}"
            candidates = [request["path"]]
            context = {"workspace": str(folder), "paths": [request["path"]], "request": request}
        allowed = await self.gate.request(title, detail, candidates, context=context)
        return None if allowed else "denied_by_operator"
