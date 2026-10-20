"""CodexBrain: drive OpenAI Codex via the ``codex app-server`` behind :class:`Brain`.

``codex app-server`` speaks bidirectional JSON-RPC 2.0. In private bridge mode
this is newline-delimited JSON over stdio; in shared TUI mode this is WebSocket
over a Unix socket opened by ``codex app-server --listen unix://...``. This
brain:

  * spawns ``codex app-server`` as a private subprocess or starts/connects to a
    shared Unix-socket listener;
  * performs the ``initialize`` -> ``initialized`` handshake;
  * starts (or resumes) a thread, sends each user turn with ``turn/start``, and
    streams assistant text from ``item/agentMessage/delta`` /
    ``item/completed`` notifications until ``turn/completed``;
  * answers server-initiated approval requests
    (``item/commandExecution/requestApproval``,
    ``item/fileChange/requestApproval``) by routing them through the SAME
    :class:`PermissionGate` the Claude path uses (off-limits pre-screen +
    Telegram permission choices + timeout). Allow -> ``accept``; Deny -> ``decline``;
    timeout -> ``cancel``.

Protocol method names, params, and the approval decision values were checked
against ``codex app-server generate-json-schema`` for the installed Codex CLI.

App Server has native thread resume, so the persisted ``.session`` file holds
the Codex *threadId* and is replayed via ``thread/resume`` on startup.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import os
import shutil
import socket
from collections import deque
from pathlib import Path
from typing import Any, AsyncIterator

from modules.brain import Brain, PermissionGate
from modules.command_activity import log_command
from modules.token_meter import estimate_tokens, subtract_usage

log = logging.getLogger("overlord.codex")

# Reasoning-effort levels Codex accepts (``model_reasoning_effort``).
EFFORT_LEVELS = ("minimal", "low", "medium", "high")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSTRUCTIONS_FILE = PROJECT_ROOT / "AGENTS.md"
HOME_INSTRUCTIONS_FILE = Path.home() / "AGENTS.md"
ENV_INSTRUCTIONS_FILE = "OVERLORD_CODEX_INSTRUCTIONS_FILE"
CODEX_USAGE_CACHE = Path.home() / ".cache" / "overlord" / "codex_usage.json"
VISIBLE_REPORT_PREFIX = "[BRIDGE/SYSTEM WORKER STATUS]"
APP_SERVER_STREAM_LIMIT_BYTES = 64 * 1024 * 1024
CONTROL_REQUEST_TIMEOUT = 2.0
DEFAULT_APP_SERVER_SOCKET = PROJECT_ROOT / "run" / "codex-app-server.sock"

# --- checked JSON-RPC surface (codex app-server) ----------------------------
# Client -> server requests
M_INITIALIZE = "initialize"
M_THREAD_START = "thread/start"
M_THREAD_RESUME = "thread/resume"
M_THREAD_INJECT_ITEMS = "thread/inject_items"
M_TURN_START = "turn/start"
M_TURN_INTERRUPT = "turn/interrupt"
M_ACCOUNT_RATE_LIMITS_READ = "account/rateLimits/read"
# Client -> server notifications
M_INITIALIZED = "initialized"
# Server -> client streaming notifications
N_AGENT_DELTA = "item/agentMessage/delta"
N_ITEM_COMPLETED = "item/completed"
N_TURN_STARTED = "turn/started"
N_TURN_COMPLETED = "turn/completed"
N_TURN_FAILED_STATUSES = {"failed", "interrupted"}
# Server -> client requests (approvals) we answer
R_EXEC_APPROVAL = "item/commandExecution/requestApproval"
R_FILECHANGE_APPROVAL = "item/fileChange/requestApproval"
APPROVAL_METHODS = {R_EXEC_APPROVAL, R_FILECHANGE_APPROVAL}
# Server -> client requests we explicitly decline (don't support interactively)
R_TOOL_USER_INPUT = "item/tool/requestUserInput"
R_MCP_ELICITATION = "mcpServer/elicitation/request"

# Approval decision values (string enum on the wire).
DECISION_ACCEPT = "accept"
DECISION_DECLINE = "decline"
DECISION_CANCEL = "cancel"


class CodexError(RuntimeError):
    """Raised for unrecoverable Codex App Server problems (binary missing, etc.)."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def _find_rate_limits(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        for key in ("rate_limits", "rateLimits"):
            rate_limits = obj.get(key)
            if isinstance(rate_limits, dict):
                return rate_limits
        for value in obj.values():
            found = _find_rate_limits(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_rate_limits(item)
            if found is not None:
                return found
    return None


def _codex_usage_from_rate_limits(
    rate_limits: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    now = now if now is not None else datetime.datetime.now(datetime.timezone.utc).timestamp()

    def window(data: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(data, dict):
            return None
        try:
            used = float(data.get("used_percent", data.get("usedPercent", 0)) or 0)
        except (TypeError, ValueError):
            used = 0.0
        resets_at = data.get("resets_at", data.get("resetsAt"))
        reset_passed = isinstance(resets_at, (int, float)) and resets_at <= now
        effective_used = 0.0 if reset_passed else used
        return {
            "used": round(effective_used, 1),
            "gas": max(0, int(round(100 - effective_used))),
            "resets_at": resets_at,
            "reset_passed": reset_passed,
        }

    windows: dict[str, Any] = {}
    for candidate in (rate_limits.get("primary"), rate_limits.get("secondary")):
        if not isinstance(candidate, dict):
            continue
        minutes = candidate.get(
            "window_minutes", candidate.get("windowDurationMins")
        )
        if minutes == 300:
            windows["session"] = window(candidate)
        elif minutes == 10080:
            windows["weekly"] = window(candidate)
    if not windows:
        return None
    return {
        "session": windows.get("session"),
        "weekly": windows.get("weekly"),
        "age_hours": 0.0,
        "plan_type": rate_limits.get("plan_type", rate_limits.get("planType")),
        "source": "codex_app_server",
    }


def _write_codex_usage_cache(usage: dict[str, Any]) -> None:
    try:
        CODEX_USAGE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CODEX_USAGE_CACHE.write_text(json.dumps(usage), encoding="utf-8")
    except OSError as exc:
        log.debug("Could not write Codex usage cache: %s", exc)


def _read_codex_usage_cache() -> dict[str, Any] | None:
    try:
        usage = json.loads(CODEX_USAGE_CACHE.read_text(encoding="utf-8"))
        if isinstance(usage, dict):
            age = datetime.datetime.now().timestamp() - CODEX_USAGE_CACHE.stat().st_mtime
            usage["age_hours"] = round(max(0, age) / 3600, 1)
            return usage
    except (OSError, ValueError, TypeError):
        pass
    return None


def _record_codex_usage_cache_from_message(msg: dict[str, Any]) -> None:
    rate_limits = _find_rate_limits(msg)
    if not rate_limits:
        return
    usage = _codex_usage_from_rate_limits(rate_limits)
    if usage is None:
        return
    _write_codex_usage_cache(usage)


class UnixWebSocketTransport:
    """Minimal WebSocket client for Codex app-server's Unix-socket transport."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.reader = reader
        self.writer = writer

    @classmethod
    async def connect(cls, path: Path) -> "UnixWebSocketTransport":
        reader, writer = await asyncio.open_unix_connection(str(path))
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = "\r\n".join(
            [
                "GET / HTTP/1.1",
                "Host: localhost",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {key}",
                "Sec-WebSocket-Version: 13",
                "",
                "",
            ]
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        header = await reader.readuntil(b"\r\n\r\n")
        status = header.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            writer.close()
            await writer.wait_closed()
            raise CodexError(
                "Codex app-server WebSocket handshake failed: "
                f"{status.decode(errors='replace')}"
            )
        return cls(reader, writer)

    async def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length <= 125:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.extend([0x80 | 126, (length >> 8) & 0xFF, length & 0xFF])
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self.writer.write(bytes(header) + mask + masked)
        await self.writer.drain()

    async def recv_text(self) -> str | None:
        fragments: list[bytes] = []
        while True:
            first = await self.reader.readexactly(1)
            second = await self.reader.readexactly(1)
            fin = bool(first[0] & 0x80)
            opcode = first[0] & 0x0F
            masked = bool(second[0] & 0x80)
            length = second[0] & 0x7F
            if length == 126:
                length = int.from_bytes(await self.reader.readexactly(2), "big")
            elif length == 127:
                length = int.from_bytes(await self.reader.readexactly(8), "big")
            mask = await self.reader.readexactly(4) if masked else b""
            payload = await self.reader.readexactly(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

            if opcode == 0x8:
                return None
            if opcode == 0x9:
                await self._send_control(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x0):
                fragments.append(payload)
                if fin:
                    return b"".join(fragments).decode("utf-8", errors="replace")

    async def _send_control(self, opcode: int, payload: bytes) -> None:
        if len(payload) > 125:
            payload = payload[:125]
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self.writer.write(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)
        await self.writer.drain()

    async def close(self) -> None:
        try:
            await self._send_control(0x8, b"")
        except Exception:
            pass
        self.writer.close()
        await self.writer.wait_closed()


class CodexBrain(Brain):
    name = "codex"
    supports_effort = True

    def __init__(
        self,
        *,
        gate: PermissionGate,
        cwd: str,
        model: str | None,
        session_file: Path,
        codex_bin: str = "codex",
        effort: str | None = None,
        approval_policy: str = "on-request",
        sandbox: str = "read-only",
        developer_instructions: str | None = None,
        app_server_proxy: bool = False,
        app_server_socket: str | None = None,
    ) -> None:
        self.gate = gate
        self.cwd = cwd
        self.model = model or None
        self.effort = (effort or "").strip().lower() or None
        self.session_file = session_file
        self.codex_bin = codex_bin
        self.approval_policy = approval_policy
        self.sandbox = sandbox
        self.app_server_proxy = app_server_proxy
        self.app_server_socket = Path(app_server_socket or DEFAULT_APP_SERVER_SOCKET)
        self.developer_instructions = (
            developer_instructions
            if developer_instructions is not None
            else _load_developer_instructions()
        )

        self._proc: asyncio.subprocess.Process | None = None
        self._listener_proc: asyncio.subprocess.Process | None = None
        self._ws: UnixWebSocketTransport | None = None
        self._thread_id: str | None = None
        self._next_id = 0
        # Pending client->server requests: id -> Future resolved with the result.
        self._pending: dict[int, asyncio.Future] = {}
        # Per-turn streaming queue; receives whole assistant messages + a None
        # sentinel at end of turn.
        self._turn_queue: asyncio.Queue[str | None] | None = None
        self._turn_error: str | None = None
        # Accumulate streamed deltas per agentMessage item so we relay one
        # coherent Telegram message instead of a flood of tiny fragments.
        self._delta_buf: dict[str, str] = {}
        self._reader_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
        self._server_requests: dict[asyncio.Task, str | None] = {}
        self._server_request_lock = asyncio.Lock()
        self._completed_turns = deque(maxlen=256)
        self._visible_report_turn_active = False
        self._active_turn_id: str | None = None
        self._active_model: str | None = self.model
        self._model_provider: str | None = None
        self._thread_token_usage: dict[str, Any] | None = None
        # Cumulative counters as of the end of the previous turn. Codex reports
        # a per-turn ``last`` block, but older app-servers only publish running
        # totals, so keep the previous snapshot and difference it as a fallback.
        self._token_usage_total: dict[str, Any] | None = None
        self._prev_token_usage_total: dict[str, Any] | None = None
        self._last_turn_token_usage: dict[str, Any] | None = None
        self.last_turn_usage: dict[str, Any] | None = None
        self.last_turn_cost_usd: float | None = None
        self.last_turn_outcome: str = "ok"
        # Set once a thread/start rejects the effort parameter, so we stop
        # sending it instead of retrying on every reconnect.
        self._effort_unsupported = False
        # mtime of the thread's rollout file at our last load — used to detect
        # terminal `codex resume` turns on the SAME thread so Telegram picks
        # them up (parity with the Claude brain). See _maybe_refresh.
        self._loaded_mtime: float = 0.0
        self._compaction_active = False
        self._compaction_done: asyncio.Event | None = None
        self._compaction_item_completed = False
        self._compaction_turn_completed = False
        self.compaction_status = "idle"

    @property
    def session_id(self) -> str | None:
        return self._thread_id

    # ---------------------------------------------------------------- transport
    def _alloc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _send(self, obj: dict[str, Any]) -> None:
        if self._ws is not None:
            await self._ws.send_text(json.dumps(obj))
            return
        if self._proc is None or self._proc.stdin is None:
            raise CodexError("Codex app-server is not running.")
        data = (json.dumps(obj) + "\n").encode()
        async with self._write_lock:
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()

    async def _request(self, method: str, params: Any) -> dict[str, Any]:
        """Send a client->server request and await its result."""
        if self._reader_task is not None and self._reader_task.done():
            raise CodexError("Codex app-server stream closed.")
        req_id = self._alloc_id()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        try:
            await self._send({"id": req_id, "method": method, "params": params})
            return await fut
        finally:
            self._pending.pop(req_id, None)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"method": method, "params": params})

    async def _respond(self, req_id: Any, result: dict[str, Any]) -> None:
        """Reply to a server->client request (e.g. an approval)."""
        await self._send({"id": req_id, "result": result})

    # ---------------------------------------------------------------- reader loop
    async def _read_loop(self) -> None:
        try:
            if self._ws is not None:
                while True:
                    text = await self._ws.recv_text()
                    if text is None:
                        break
                    if not text.strip():
                        continue
                    try:
                        msg = json.loads(text)
                    except json.JSONDecodeError:
                        log.debug("Non-JSON websocket message from codex: %s", text[:200])
                        continue
                    await self._dispatch(msg)
            else:
                assert self._proc is not None and self._proc.stdout is not None
                stdout = self._proc.stdout
                while True:
                    line = await stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        log.debug("Non-JSON line from codex: %s", line[:200])
                        continue
                    await self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Codex reader loop crashed")
        finally:
            # Unblock anyone waiting on the process if it died.
            self._cancel_server_requests()
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(CodexError("Codex app-server stream closed."))
            self._pending.clear()
            if self._compaction_active:
                self._turn_error = self._turn_error or "Codex stream closed; compaction completion is unknown."
                self.compaction_status = "uncertain"
                self.last_turn_outcome = "error"
                if self._compaction_done is not None:
                    self._compaction_done.set()
            if self._turn_queue is not None:
                self._turn_error = self._turn_error or "Codex app-server stream closed."
                self._turn_queue.put_nowait(None)

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        _record_codex_usage_cache_from_message(msg)

        # 1) Response to one of our requests.
        if "id" in msg and "method" not in msg:
            fut = self._pending.pop(msg["id"], None)
            if fut is None or fut.done():
                return
            if "error" in msg:
                error = msg["error"]
                fut.set_exception(CodexError(
                    str(error), code=error.get("code") if isinstance(error, dict) else None,
                ))
            else:
                fut.set_result(msg.get("result", {}))
            return

        method = msg.get("method")
        if method is None:
            return

        # 2) Server-initiated request (has an id) -> we must reply.
        if "id" in msg:
            # Operator waits must not block RPC replies or turn notifications.
            task = asyncio.create_task(self._serve_server_request(msg))
            self._server_requests[task] = (msg.get("params") or {}).get("turnId")
            task.add_done_callback(self._server_request_finished)
            return

        # 3) Notification (no id).
        self._handle_notification(method, msg.get("params") or {})

    # ---------------------------------------------------------------- approvals
    async def _serve_server_request(self, msg: dict[str, Any]) -> None:
        try:
            async with self._server_request_lock:
                await self._handle_server_request(msg)
        except asyncio.CancelledError:
            try:
                async with asyncio.timeout(CONTROL_REQUEST_TIMEOUT):
                    await self._respond(msg.get("id"), self._decline_result(msg.get("method")))
            except Exception:
                pass
            raise
        except Exception:
            await self._respond(msg.get("id"), self._decline_result(msg.get("method")))

    @staticmethod
    def _decline_result(method: str | None) -> dict[str, Any]:
        if method == R_TOOL_USER_INPUT:
            return {"answers": {}}
        return {"decision": DECISION_CANCEL if method in APPROVAL_METHODS else DECISION_DECLINE}

    def _server_request_finished(self, task: asyncio.Task) -> None:
        self._server_requests.pop(task, None)
        if not task.cancelled() and task.exception() is not None:
            log.warning("Codex interactive request handler failed.")

    def _cancel_server_requests(self, turn_id: str | None = None) -> None:
        for task, requested_turn in list(self._server_requests.items()):
            if turn_id is None or requested_turn is None or requested_turn == turn_id:
                task.cancel()

    async def _handle_server_request(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}

        if params.get("threadId") and params["threadId"] != self._thread_id:
            await self._respond(req_id, self._decline_result(method))
            return

        # Recheck after acquiring the ordering lock: completion may arrive while
        # this request is queued, or before the server delivers a late request.
        requested_turn = params.get("turnId")
        if requested_turn and (self._thread_id, requested_turn) in self._completed_turns:
            await self._respond(req_id, self._decline_result(method))
            return

        if self._visible_report_turn_active or self._compaction_active:
            await self._decline_visible_report_request(req_id, method)
            return

        if method in APPROVAL_METHODS:
            allow = await self._approve(method, params)
            decision = DECISION_ACCEPT if allow else DECISION_DECLINE
            await self._respond(req_id, {"decision": decision})
            return

        if method == R_TOOL_USER_INPUT:
            await self._respond(req_id, await self._request_user_input(params))
            return

        if method == R_MCP_ELICITATION:
            log.info("Declining unsupported server request %s", method)
            await self._respond(req_id, {"decision": DECISION_DECLINE})
            return

        # Unknown server request: respond with a benign decline so the turn isn't
        # wedged waiting on us.
        log.warning("Unknown server request %s; declining", method)
        await self._respond(req_id, {"decision": DECISION_DECLINE})

    async def _decline_visible_report_request(
        self, req_id: Any, method: str | None
    ) -> None:
        """Keep opt-in report turns from taking actions or prompting Ben."""
        log.warning("Declining %s during bridge visible worker-report turn", method)
        await self._respond(req_id, self._decline_result(method))

    async def _request_user_input(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Render Codex request_user_input questions as Telegram buttons."""
        answers: dict[str, dict[str, list[str]]] = {}
        questions = params.get("questions")
        if not isinstance(questions, list):
            return {"answers": answers}
        if len(questions) > 4:
            return {"answers": answers}
        keys = [q.get("id") if isinstance(q, dict) else None for q in questions]
        if (any(not isinstance(key, str) or not key.strip() for key in keys)
                or len({key.strip() for key in keys}) != len(keys)
                or any(not isinstance(q.get("question"), str) or not q["question"].strip()
                       for q in questions)):
            return {"answers": {}}
        if any(q.get("isSecret") for q in questions):
            self.gate.telegram.send(self.gate.owner,
                "🔒 Codex requested secret input. Overlord will not collect secrets through Telegram.")
            return {"answers": {}}
        review = []
        raw_answers = {}
        for index, item in enumerate(questions):
            if not isinstance(item, dict):
                continue
            question_id = str(item.get("id") or "").strip()
            question = str(item.get("question") or "").strip()
            if not question_id or not question:
                continue
            if question_id in answers:
                return {"answers": {}}
            if item.get("isSecret"):
                self.gate.telegram.send(
                    self.gate.owner,
                    "🔒 Codex requested secret input. Overlord will not collect "
                    "secrets through Telegram.",
                )
                return {"answers": {}}
            header = str(item.get("header") or "Question").strip()
            options = []
            for option in item.get("options") or []:
                if not isinstance(option, dict):
                    continue
                label = str(option.get("label") or "").strip()
                if label:
                    options.append(
                        (label, str(option.get("description") or "").strip())
                    )
            prompt = f"❓ {header}\n\n{question}"
            if len(questions) > 1:
                prompt = f"Question {index + 1} of {len(questions)}\n\n" + prompt
            answer = await self.gate.choose(prompt, options[:8])
            if not answer:
                return {"answers": {}}
            answers[question_id] = {"answers": [answer] if answer else []}
            raw_answers[question_id] = answer
            review.append({"key": question_id, "prompt": prompt, "options": options[:8]})
        if len(review) > 1:
            reviewed = await self.gate.review_answers(review, raw_answers)
            if reviewed is None:
                return {"answers": {}}
            answers = {key: {"answers": [value]} for key, value in reviewed.items()}
        return {"answers": answers}

    async def _approve(self, method: str, params: dict[str, Any]) -> bool:
        """Route a Codex approval through the shared gate. True=accept."""
        action = {
            key: value for key, value in params.items()
            if key not in {"turnId", "itemId", "approvalId", "requestId"}
        }
        if method == R_EXEC_APPROVAL:
            command = params.get("command") or ""
            cwd = params.get("cwd") or ""
            detail = (
                " ".join(str(part) for part in command)
                if isinstance(command, list) else str(command)
            ) or "(command execution)"
            if cwd:
                detail = f"{detail}\n(cwd: {cwd})"
            candidates = (
                [str(part) for part in command]
                if isinstance(command, list) else [str(command)]
            ) + [cwd]
            return await self.gate.request(
                "Codex: run command", detail, candidates,
                context={"workspace": self.cwd, "request": action},
            )

        # File-change approval. The params don't always carry the path inline,
        # so surface the reason and let the operator decide after the shared
        # gate checks any grant root Codex provided.
        reason = params.get("reason") or "Codex wants to write file changes."
        grant_root = params.get("grantRoot") or ""
        candidates = [grant_root]
        return await self.gate.request(
            "Codex: apply file changes", reason, candidates,
            context={
                "workspace": self.cwd, "request": action,
                "paths": [grant_root] if grant_root else [],
            },
        )

    # ---------------------------------------------------------------- streaming
    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        thread_id = params.get("threadId")
        if thread_id and self._thread_id and thread_id != self._thread_id:
            return
        if method in {"item/started", N_ITEM_COMPLETED}:
            item = params.get("item") or {}
            if item.get("type") == "commandExecution":
                log_command("codex", "started" if method == "item/started" else item.get("status", "completed"),
                            item.get("command", ""), item.get("cwd", self.cwd),
                            exit_code=item.get("exitCode"))
            if item.get("type") == "contextCompaction":
                self.compaction_status = (
                    "running" if method == "item/started" else "completed"
                )
                if method == N_ITEM_COMPLETED:
                    self._compaction_item_completed = True
                    if self._compaction_done is not None and self._compaction_turn_completed:
                        self._compaction_active = False
                        self._compaction_done.set()
        if method == "thread/tokenUsage/updated":
            token_usage = params.get("tokenUsage")
            if isinstance(token_usage, dict):
                total = token_usage.get("total")
                if isinstance(total, dict):
                    last = token_usage.get("last")
                    self._token_usage_total = dict(total)
                    if isinstance(last, dict):
                        # Codex already isolates the current turn for us; keep
                        # the whole block so in/out/cached survive to the ledger
                        # instead of being flattened to a single total.
                        self._last_turn_token_usage = dict(last)
                    self._thread_token_usage = {
                        **total,
                        "lastTotalTokens": (
                            last.get("totalTokens") if isinstance(last, dict) else None
                        ),
                        "modelContextWindow": token_usage.get("modelContextWindow"),
                    }
            return

        if method == N_AGENT_DELTA:
            # Buffer deltas per item; flush as one message on item/completed so
            # Telegram gets coherent replies, not a flood of fragments.
            item_id = params.get("itemId") or ""
            delta = params.get("delta") or ""
            if delta:
                self._delta_buf[item_id] = self._delta_buf.get(item_id, "") + delta
            return

        if method == N_ITEM_COMPLETED:
            item = params.get("item") or {}
            if item.get("type") != "agentMessage":
                self._delta_buf.pop(item.get("id", ""), None)
                return
            item_id = item.get("id") or ""
            # Prefer the authoritative final text; fall back to buffered deltas.
            text = item.get("text") or self._delta_buf.get(item_id, "")
            self._delta_buf.pop(item_id, None)
            if text and text.strip() and self._turn_queue is not None:
                self._turn_queue.put_nowait(text)
            return

        if method == N_TURN_STARTED:
            turn = params.get("turn") or {}
            turn_id = turn.get("id")
            if isinstance(turn_id, str) and turn_id.strip():
                self._active_turn_id = turn_id
            return

        if method == N_TURN_COMPLETED:
            turn = params.get("turn") or {}
            turn_id = turn.get("id")
            if isinstance(turn_id, str) and turn_id:
                self._completed_turns.append((self._thread_id, turn_id))
            self._cancel_server_requests(turn_id)
            if isinstance(turn_id, str) and turn_id == self._active_turn_id:
                self._active_turn_id = None
            status = turn.get("status")
            if isinstance(status, dict):
                status = status.get("type")
            if status in N_TURN_FAILED_STATUSES:
                err = (turn.get("error") or {})
                # An earlier "error" notification carries the real cause; only
                # fall back to the generic text when nothing better was captured.
                self._turn_error = (
                    (err.get("message") if isinstance(err, dict) else None)
                    or self._turn_error
                    or f"Codex turn {status}."
                )
                if self._compaction_active:
                    self.compaction_status = "failed"
                    self._compaction_active = False
                    if self._compaction_done is not None:
                        self._compaction_done.set()
            elif self._compaction_active and status == "completed":
                self._compaction_turn_completed = True
                if self._compaction_item_completed:
                    self.compaction_status = "completed"
                    self._compaction_active = False
                    if self._compaction_done is not None:
                        self._compaction_done.set()
            if self._turn_queue is not None:
                self._turn_queue.put_nowait(None)
            return

        if method == "error":
            log.error("Codex error notification: %s", params)
            err = params.get("error")
            if isinstance(err, dict) and err.get("message"):
                # Capture so query() surfaces the real cause; turn/completed's
                # generic "failed" would otherwise mask it.
                self._turn_error = err["message"]
            return

    # ---------------------------------------------------------------- session
    def _load_thread_id(self) -> str | None:
        try:
            sid = self.session_file.read_text().strip()
            return sid or None
        except FileNotFoundError:
            return None

    def _save_thread_id(self, thread_id: str) -> None:
        if thread_id and thread_id != self._thread_id:
            self._thread_id = thread_id
            try:
                self.session_file.write_text(thread_id)
            except OSError as exc:
                log.error("Could not persist Codex thread id: %s", exc)

    # ------------------------------------------------- shared-session detection
    def _rollout_path(self, tid: str | None) -> Path | None:
        """Newest rollout transcript for thread ``tid`` (date-nested store)."""
        if not tid:
            return None
        matches = sorted(
            Path.home().glob(f".codex/sessions/**/rollout-*-{tid}.jsonl")
        )
        return matches[-1] if matches else None

    def _rollout_mtime(self, tid: str | None) -> float:
        path = self._rollout_path(tid)
        if path is None:
            return 0.0
        try:
            return path.stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def _record_mtime(self) -> None:
        self._loaded_mtime = self._rollout_mtime(self._thread_id)

    def _set_active_turn_id_from_result(self, result: dict[str, Any]) -> None:
        turn = result.get("turn") or {}
        turn_id = turn.get("id")
        if isinstance(turn_id, str) and turn_id.strip():
            self._active_turn_id = turn_id

    async def _maybe_refresh(self) -> None:
        """Reload the thread from disk if it changed outside this process.

        Either the pinned id in the session file changed (a new shared thread was
        started from the terminal) or the same thread's rollout grew because Ben
        ran ``codex resume`` in a terminal. Re-issue ``thread/resume`` so Telegram
        reflects terminal work — parity with ClaudeBrain._maybe_refresh.
        """
        disk_tid = self._load_thread_id()
        target = None
        if disk_tid and disk_tid != self._thread_id:
            log.info("Shared Codex thread changed (%s -> %s); reloading",
                     self._thread_id, disk_tid)
            target = disk_tid
        elif self._thread_id and self._rollout_mtime(self._thread_id) > self._loaded_mtime + 0.001:
            log.info("Codex thread %s changed on disk (external turn); reloading",
                     self._thread_id)
            target = self._thread_id
        if target is None:
            return
        try:
            # Re-issue thread/resume without creating a replacement thread if
            # this best-effort refresh fails.
            await self._start_thread(target, fallback_to_fresh=False)
            self._record_mtime()
        except Exception as exc:
            log.error("Codex reload failed (%s); keeping current thread", exc)

    # ---------------------------------------------------------------- lifecycle
    async def _spawn(self) -> None:
        if shutil.which(self.codex_bin) is None:
            raise CodexError(
                f"Codex CLI '{self.codex_bin}' not found on PATH. Install it "
                "(npm i -g @openai/codex) or set OVERLORD_CODEX_BIN to the binary."
            )
        if self.app_server_proxy:
            await self._ensure_app_server_socket()
            self._ws = await UnixWebSocketTransport.connect(self.app_server_socket)
            self._reader_task = asyncio.create_task(self._read_loop())
            return
        else:
            argv = [self.codex_bin, "app-server"]
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # App-server can emit whole-thread JSONL notifications during resume.
            # Python's default StreamReader limit is 64 KiB, which is too small
            # for active Overlord threads and can kill worker-report handling.
            limit=APP_SERVER_STREAM_LIMIT_BYTES,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        # Drain stderr to the log so codex warnings/errors are visible.
        asyncio.create_task(self._drain_stderr())

    async def _ensure_app_server_socket(self) -> None:
        """Start a shared Unix-socket app-server for remote TUI mode."""
        if self._unix_socket_accepts_connections(self.app_server_socket):
            log.info("Codex app-server socket already listening at %s", self.app_server_socket)
            return

        self.app_server_socket.parent.mkdir(parents=True, exist_ok=True)
        self.app_server_socket.unlink(missing_ok=True)

        if not await self._start_shared_app_server_listener():
            self._listener_proc = await asyncio.create_subprocess_exec(
                self.codex_bin,
                "app-server",
                "--listen",
                f"unix://{self.app_server_socket}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=APP_SERVER_STREAM_LIMIT_BYTES,
            )
            asyncio.create_task(
                self._drain_stream(
                    self._listener_proc.stdout, "codex app-server listener stdout"
                )
            )
            asyncio.create_task(
                self._drain_stream(
                    self._listener_proc.stderr, "codex app-server listener stderr"
                )
            )

        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            if self._unix_socket_accepts_connections(self.app_server_socket):
                log.info(
                    "Codex app-server listener ready at %s; using websocket transport",
                    self.app_server_socket,
                )
                return
            if self._listener_proc is not None and self._listener_proc.returncode is not None:
                raise CodexError(
                    f"Codex app-server listener exited with {self._listener_proc.returncode}."
                )
            await asyncio.sleep(0.1)
        raise CodexError(
            f"Timed out waiting for Codex app-server socket {self.app_server_socket}."
        )

    async def _start_shared_app_server_listener(self) -> bool:
        systemd_run = shutil.which("systemd-run")
        systemctl = shutil.which("systemctl")
        codex_bin = shutil.which(self.codex_bin) or self.codex_bin
        if not systemd_run or not systemctl:
            return False

        unit = "overlord-codex-app-server.service"
        stop_proc = await asyncio.create_subprocess_exec(
            systemctl,
            "--user",
            "stop",
            unit,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await stop_proc.wait()
        proc = await asyncio.create_subprocess_exec(
            systemd_run,
            "--user",
            "--quiet",
            "--collect",
            f"--unit={unit.removesuffix('.service')}",
            "--property=Restart=on-failure",
            "--property=RestartSec=1",
            codex_bin,
            "app-server",
            "--listen",
            f"unix://{self.app_server_socket}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            log.warning(
                "Could not start shared Codex app-server via systemd-run: %s%s",
                (out or b"").decode(errors="replace"),
                (err or b"").decode(errors="replace"),
            )
            return False
        log.info("Started shared Codex app-server as user unit %s", unit)
        return True

    @staticmethod
    def _unix_socket_accepts_connections(path: Path) -> bool:
        if not path.exists():
            return False
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.25)
            sock.connect(str(path))
        except OSError:
            return False
        finally:
            sock.close()
        return True

    async def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        await self._drain_stream(self._proc.stderr, "codex stderr")

    async def _drain_stream(
        self, stream: asyncio.StreamReader | None, label: str
    ) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            log.debug("%s: %s", label, line.decode(errors="replace").rstrip())

    async def _handshake(self) -> None:
        await self._request(
            M_INITIALIZE,
            {
                "clientInfo": {"name": "overlord-bridge", "version": "0.1.0"},
            },
        )
        await self._notify(M_INITIALIZED, {})

    async def _start_thread(
        self, resume: str | None, *, fallback_to_fresh: bool = True
    ) -> None:
        common: dict[str, Any] = {
            "cwd": self.cwd,
            "approvalPolicy": self.approval_policy,
            "sandbox": self.sandbox,
        }
        if self.developer_instructions:
            common["developerInstructions"] = self.developer_instructions
        if self.model:
            common["model"] = self.model
        if self.effort and not self._effort_unsupported:
            common["effort"] = self.effort

        async def call(method: str, params: dict[str, Any]) -> dict[str, Any]:
            """Issue a thread request, retrying once without ``effort``.

            ``effort`` is a newer app-server parameter. Rather than pin a Codex
            version, send it optimistically and drop it permanently the first
            time a server rejects it — an old Codex keeps working, a new one
            gets the setting.
            """
            try:
                return await self._request(method, params)
            except CodexError as exc:
                if "effort" not in params:
                    raise
                log.warning(
                    "Codex rejected the effort parameter (%s); "
                    "continuing without it.",
                    exc,
                )
                self._effort_unsupported = True
                stripped = {k: v for k, v in params.items() if k != "effort"}
                return await self._request(method, stripped)

        if resume:
            try:
                result = await call(M_THREAD_RESUME, {**common, "threadId": resume})
            except CodexError as exc:
                if not fallback_to_fresh:
                    raise
                log.warning("Codex resume of %s failed (%s); starting fresh.", resume, exc)
                # The pin is replaced by _save_thread_id below once the new thread
                # exists; deleting it first would lose it if app-server is down.
                result = await call(M_THREAD_START, dict(common))
        else:
            result = await call(M_THREAD_START, dict(common))

        thread = result.get("thread") or {}
        thread_id = thread.get("id")
        if not thread_id:
            raise CodexError(f"Codex did not return a thread id: {result}")
        self._active_model = result.get("model") or self.model or "default"
        self._model_provider = result.get("modelProvider")
        self._thread_token_usage = None
        self._token_usage_total = None
        self._prev_token_usage_total = None
        self._last_turn_token_usage = None
        self._save_thread_id(thread_id)

    async def connect(self, resume: str | None = None) -> None:
        sid = resume if resume is not None else self._load_thread_id()
        await self._spawn()
        await self._handshake()
        await self._start_thread(sid)
        self._record_mtime()
        log.info(
            "CodexBrain online (cwd=%s, model=%s, sandbox=%s, approval=%s, "
            "instructions=%s, resumed=%s, thread=%s)",
            self.cwd,
            self.model or "<default>",
            self.sandbox,
            self.approval_policy,
            "yes" if self.developer_instructions else "no",
            sid is not None,
            self._thread_id,
        )

    async def routing_model_ids(self) -> set[str]:
        """Read the visible native catalog, without claiming account entitlement."""
        models = set()
        cursors = set()
        cursor = None
        async with asyncio.timeout(5):
            for _ in range(10):
                page = await self._request("model/list", {
                    "cursor": cursor, "limit": 100, "includeHidden": False})
                data = page.get("data")
                if not isinstance(data, list) or len(data) > 100:
                    raise ValueError("Invalid native model catalog")
                for entry in data:
                    if not isinstance(entry, dict) or not isinstance(entry.get("hidden"), bool):
                        raise ValueError("Invalid native model entry")
                    model = entry.get("model")
                    if not isinstance(model, str) or not model.strip():
                        raise ValueError("Invalid native model ID")
                    if entry["hidden"]:
                        continue
                    if model in models:
                        raise ValueError("Duplicate native model ID")
                    models.add(model)
                cursor = page.get("nextCursor")
                if cursor is None:
                    return models
                if not isinstance(cursor, str) or not cursor or cursor in cursors:
                    raise ValueError("Invalid native catalog cursor")
                cursors.add(cursor)
        raise ValueError("Native model catalog exceeds page budget")

    async def model_options(self) -> list[tuple[str, str]]:
        try:
            names = sorted(await self.routing_model_ids())
        except Exception as exc:  # noqa: BLE001 - fall back to the configured model
            log.info("Codex model catalog unavailable for /model: %s", exc)
            names = []
        if self.model and self.model not in names:
            names.append(self.model)
        return [(name, "") for name in names]

    async def effort_options(self) -> list[tuple[str, str]]:
        return [("default", "engine default")] + [(level, "") for level in EFFORT_LEVELS]

    async def reset(self) -> None:
        self._cancel_server_requests()
        self.session_file.unlink(missing_ok=True)
        self._thread_id = None
        self._compaction_active = False
        self.compaction_status = "idle"
        await self._start_thread(None)
        self._record_mtime()
        log.info("Codex thread reset via /new (new thread=%s)", self._thread_id)

    async def disconnect(self) -> None:
        self._cancel_server_requests()
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._proc is not None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
            except Exception:
                pass
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        # In shared TUI mode the app-server owns the user's live terminal socket.
        # Leave it running across bridge restarts; the next bridge process will reconnect.

    async def status(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch current rate limits without consuming a model turn."""
        usage: dict[str, Any] | None = None
        usage_note: str | None = None
        try:
            result = await asyncio.wait_for(
                self._request(M_ACCOUNT_RATE_LIMITS_READ, None), timeout=5
            )
            rate_limits = _find_rate_limits(result)
            if rate_limits is not None:
                usage = _codex_usage_from_rate_limits(rate_limits)
                if usage is not None:
                    _write_codex_usage_cache(usage)
        except Exception as exc:  # noqa: BLE001 - cached status remains useful
            log.warning("Could not refresh Codex rate limits for /status: %s", exc)
            usage_note = "Usage is from the last cached update."
        if usage is None:
            usage = _read_codex_usage_cache()
            if usage is not None and usage_note is None:
                usage_note = "Usage is from the last cached update."
        return {
            "brain": self.name,
            "model": self._active_model or self.model or "default",
            "effort": self.effort,
            "model_provider": self._model_provider,
            "session_id": self.session_id,
            "usage": usage,
            "usage_note": usage_note,
            "tokens": self._thread_token_usage,
        }

    # ------------------------------------------------------------- runtime knobs
    async def _restart_thread_in_place(self, what: str) -> str | None:
        """Re-open the CURRENT thread so a new model/effort takes effect.

        Codex binds the model to the thread at start time, so unlike Claude this
        cannot be a field change alone. Resuming the same thread id keeps the
        conversation intact — the operator changes gears, not topics. On failure
        the previous value is already gone from the object, so the caller
        restores it.
        """
        if self._thread_id is None:
            return None
        try:
            await self._start_thread(self._thread_id, fallback_to_fresh=False)
        except Exception as exc:  # noqa: BLE001 - report, never kill the bridge
            log.warning("Could not apply the new %s to the Codex thread: %s", what, exc)
            return f"Codex refused the new {what}: {exc}"
        return None

    async def set_model(self, model: str) -> str | None:
        name = (model or "").strip()
        if not name:
            return "Give a model name, e.g. /model gpt-5-codex"
        previous = self.model
        self.model = name
        error = await self._restart_thread_in_place("model")
        if error is not None:
            self.model = previous
            return error
        self._active_model = name
        return None

    async def set_effort(self, effort: str) -> str | None:
        level = (effort or "").strip().lower()
        if level not in ("", "default", "auto", "off", "none") and level not in EFFORT_LEVELS:
            return f"Unknown effort {level!r}. Choose: {', '.join(EFFORT_LEVELS)}"
        previous = self.effort
        self.effort = None if level in ("", "default", "auto", "off", "none") else level
        error = await self._restart_thread_in_place("effort")
        if error is not None:
            self.effort = previous
            return error
        if self._effort_unsupported:
            self.effort = previous  # the server ignores it, so do not claim it
            return (
                "This Codex build does not accept a reasoning-effort setting; "
                "nothing was changed."
            )
        return None

    async def count_input_tokens(self, text: str) -> tuple[int | None, str]:
        """Codex exposes no counting endpoint, so quote from the local model."""
        if not text.strip():
            return 0, "estimate"
        return estimate_tokens(text), "estimate"

    async def query(self, text: str) -> AsyncIterator[str]:
        if self._compaction_active:
            raise RuntimeError("Compaction has not settled; inspect /context first.")
        if self._thread_id is None:
            raise RuntimeError("CodexBrain.query called before connect()")
        # Per-turn accounting starts clean so a turn that reports nothing can't
        # be recorded twice off the previous turn's numbers.
        self.last_turn_usage = None
        self.last_turn_cost_usd = None
        self.last_turn_outcome = "ok"
        self._last_turn_token_usage = None
        self._prev_token_usage_total = (
            dict(self._token_usage_total)
            if isinstance(self._token_usage_total, dict)
            else None
        )
        # Pull in any terminal `codex resume` turns on this thread first.
        await self._maybe_refresh()
        self._turn_queue = asyncio.Queue()
        self._turn_error = None
        self._delta_buf.clear()

        # The request is inside the try so a rejected turn/start still clears
        # the queue; a stale one makes compact() think a turn is in flight.
        try:
            result = await self._request(
                M_TURN_START,
                {
                    "threadId": self._thread_id,
                    "input": [{"type": "text", "text": text}],
                    **({"model": self.model} if self.model else {}),
                },
            )
            self._set_active_turn_id_from_result(result)

            while True:
                chunk = await self._turn_queue.get()
                if chunk is None:
                    break
                if chunk.strip():
                    yield chunk
        finally:
            self._turn_queue = None
            self._cancel_server_requests(self._active_turn_id)
            # Book the usage here, not after the loop: /stop and /steer cancel
            # this generator mid-await, so anything below the try would never
            # run and an interrupted turn's tokens would go unreported.
            self.last_turn_usage = self._resolve_turn_usage()
            if self._turn_error:
                self.last_turn_outcome = "error"

        # Our own turn just bumped the rollout mtime; record it so the next
        # refresh only fires on genuinely external (terminal) changes.
        self._record_mtime()

        if self._turn_error:
            yield f"⚠️ {self._turn_error}"

    def _resolve_turn_usage(self) -> dict[str, Any] | None:
        """Per-turn counters: Codex's own ``last`` block, else a total delta."""
        if isinstance(self._last_turn_token_usage, dict):
            return dict(self._last_turn_token_usage)
        if isinstance(self._token_usage_total, dict):
            delta = subtract_usage(self._token_usage_total, self._prev_token_usage_total)
            if any(value > 0 for value in delta.values()):
                return delta
        return None

    async def compact(self, *, timeout: float = 120) -> str | None:
        """Wait for contextCompaction completion, not just the RPC acknowledgement."""
        self.last_turn_usage = None
        self.last_turn_cost_usd = None
        self.last_turn_outcome = "ok"
        if not self._thread_id:
            return "No Codex conversation is loaded."
        if self._compaction_active or self._active_turn_id or self._turn_queue:
            return "Codex has an active operation; compaction was not started."
        self._prev_token_usage_total = (
            dict(self._token_usage_total) if self._token_usage_total else None
        )
        self._last_turn_token_usage = None
        self._turn_error = None
        self._compaction_done = asyncio.Event()
        self._compaction_item_completed = False
        self._compaction_turn_completed = False
        self._compaction_active = True
        self.compaction_status = "running"
        try:
            async with asyncio.timeout(timeout):
                await self._request("thread/compact/start", {"threadId": self._thread_id})
                await self._compaction_done.wait()
            if self.compaction_status == "completed":
                self._record_mtime()
                return None
            self.last_turn_outcome = "error"
            return self._turn_error or "Codex compaction failed."
        except asyncio.CancelledError:
            self.compaction_status = "uncertain"
            await self.interrupt_active_turn()
            raise
        except asyncio.TimeoutError:
            self.compaction_status = "uncertain"
            self.last_turn_outcome = "error"
            return "Compaction timed out; completion is unknown. Inspect /context."
        except Exception as exc:
            rejected = isinstance(exc, CodexError) and exc.code is not None
            self.compaction_status = "failed" if rejected else "uncertain"
            self._compaction_active = not rejected
            self.last_turn_outcome = "error"
            return f"Native compaction could not complete: {exc}"
        finally:
            self.last_turn_usage = self._resolve_turn_usage()

    async def record_event(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """Append a bridge-owned status item to the Codex thread history.

        The local app-server schema exposes ``thread/inject_items`` for raw
        Responses API items. Use a developer-role message so the report is
        clearly bridge/system context rather than Ben's words, and do not start
        a model turn.
        """
        if self._thread_id is None or not text.strip():
            return False

        await self._maybe_refresh()

        meta = metadata or {}
        safe_event_id = _safe_worker_report_event_id(meta)
        item = {
            "type": "message",
            "role": "developer",
            "id": f"bridge-worker-report-{safe_event_id}",
            "content": [{"type": "input_text", "text": text}],
            "internal_chat_message_metadata_passthrough": {
                "turn_id": f"bridge-worker-report-{safe_event_id}",
            },
        }

        try:
            await self._request(
                M_THREAD_INJECT_ITEMS,
                {"threadId": self._thread_id, "items": [item]},
            )
        except Exception as exc:  # noqa: BLE001 - best-effort audit path
            log.warning("Could not inject bridge event into Codex thread: %s", exc)
            return False

        self._record_mtime()
        return True

    async def interrupt_active_turn(self, turn_id: str | None = None) -> bool:
        """Interrupt an active turn on this thread, if one is known."""
        target_turn_id = turn_id or self._active_turn_id
        if self._thread_id is None or target_turn_id is None:
            return False
        try:
            async with asyncio.timeout(CONTROL_REQUEST_TIMEOUT):
                await self._request(
                    M_TURN_INTERRUPT,
                    {"threadId": self._thread_id, "turnId": target_turn_id},
                )
        except Exception as exc:  # noqa: BLE001 - best-effort control path
            log.warning("Could not interrupt Codex turn %s: %s", target_turn_id, exc)
            return False
        if target_turn_id == self._active_turn_id:
            self._active_turn_id = None
        return True

    async def record_visible_event(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """Start an opt-in visible worker-report turn in Codex.

        The turn is intentionally narrow: it asks Codex to emit a terse tagged
        assistant status message and sets a guard so any approval/tool request
        that happens during the turn is declined without involving Telegram.
        """
        if self._thread_id is None or not text.strip():
            return False

        await self._maybe_refresh()

        meta = metadata or {}
        safe_event_id = _safe_worker_report_event_id(meta)

        active_turn_id = self._active_turn_id
        external_active_turn_id = None
        if active_turn_id is None:
            external_active_turn_id = self._external_active_rollout_turn_id()
            active_turn_id = external_active_turn_id

        if active_turn_id is not None and not self._visible_report_turn_active:
            interrupted = await self.interrupt_active_turn(active_turn_id)
            if not interrupted and external_active_turn_id is None:
                log.warning(
                    "Codex visible worker report skipped; active turn could not be interrupted"
                )
                return False
            if self._turn_queue is not None:
                await self._wait_for_current_turn_to_settle()
            if external_active_turn_id is not None and interrupted:
                await self._wait_for_rollout_turn_to_settle(external_active_turn_id)
            if self._turn_queue is not None:
                log.warning(
                    "Codex visible worker report skipped; active turn is still running"
                )
                return False

        self._turn_queue = asyncio.Queue()
        self._turn_error = None
        self._delta_buf.clear()
        self._visible_report_turn_active = True
        chunks: list[str] = []
        try:
            result = await self._request(
                M_TURN_START,
                {
                    "threadId": self._thread_id,
                    "clientUserMessageId": (
                        f"bridge-visible-worker-report-{safe_event_id}"
                    ),
                    **({"model": self.model} if self.model else {}),
                    "input": [
                        {
                            "type": "text",
                            "text": _format_visible_worker_report_prompt(text),
                        }
                    ],
                },
            )
            self._set_active_turn_id_from_result(result)

            while True:
                chunk = await self._turn_queue.get()
                if chunk is None:
                    break
                if chunk.strip():
                    chunks.append(chunk)
        except Exception as exc:  # noqa: BLE001 - optional visibility path
            log.warning("Could not start Codex visible worker report turn: %s", exc)
            return False
        finally:
            self._visible_report_turn_active = False
            self._turn_queue = None
            self._record_mtime()

        if self._turn_error:
            log.warning(
                "Codex visible worker report turn ended with error: %s",
                self._turn_error,
            )
            return False
        if not "".join(chunks).strip():
            log.warning("Codex visible worker report turn produced no assistant text")
            return False
        return True

    async def _wait_for_current_turn_to_settle(self, timeout: float = 10.0) -> None:
        """Wait for the current streamed turn to finish after an interrupt."""
        deadline = asyncio.get_running_loop().time() + timeout
        while self._turn_queue is not None and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)

    async def _wait_for_rollout_turn_to_settle(
        self, turn_id: str, timeout: float = 10.0
    ) -> None:
        """Wait for an externally-started rollout turn to finish after interrupt."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if not self._rollout_turn_is_active(turn_id):
                return
            await asyncio.sleep(0.05)

    def _external_active_rollout_turn_id(self) -> str | None:
        """Infer an in-flight turn started by another Codex client, if any."""
        path = self._rollout_path(self._thread_id)
        if path is None:
            return None

        latest_turn_id: str | None = None
        completed_turn_ids: set[str] = set()
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    typ = event.get("type")
                    payload = event.get("payload") or {}
                    if typ == "turn_context":
                        turn_id = payload.get("turn_id")
                        if isinstance(turn_id, str) and turn_id.strip():
                            latest_turn_id = turn_id
                    elif typ == "event_msg" and payload.get("type") == "task_complete":
                        turn_id = payload.get("turn_id")
                        if isinstance(turn_id, str) and turn_id.strip():
                            completed_turn_ids.add(turn_id)
        except OSError as exc:
            log.warning("Could not inspect Codex rollout for active turn: %s", exc)
            return None

        if latest_turn_id and latest_turn_id not in completed_turn_ids:
            return latest_turn_id
        return None

    def _rollout_turn_is_active(self, turn_id: str) -> bool:
        """Return True until the rollout records task completion for turn_id."""
        path = self._rollout_path(self._thread_id)
        if path is None:
            return False
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") != "event_msg":
                        continue
                    payload = event.get("payload") or {}
                    if (
                        payload.get("type") == "task_complete"
                        and payload.get("turn_id") == turn_id
                    ):
                        return False
        except OSError as exc:
            log.warning("Could not inspect Codex rollout turn state: %s", exc)
            return False
        return True


def _load_developer_instructions() -> str:
    """Load Overlord role rules for Codex threads.

    Codex app-server runs with cwd at the home root for the Overlord, so it will
    not naturally discover this repository's AGENTS.md. Pass the instructions
    explicitly at thread start/resume instead of relying on a home-level symlink.
    """
    override = os.environ.get(ENV_INSTRUCTIONS_FILE, "").strip()
    candidates = (
        [Path(override).expanduser()]
        if override
        else [DEFAULT_INSTRUCTIONS_FILE, HOME_INSTRUCTIONS_FILE]
    )

    for path in candidates:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.warning("Could not read Codex instruction file %s: %s", path, exc)
            continue
        # UTF-8 first: these files hold em dashes and quotes, which the Windows
        # default codec turns into mojibake inside the prompt. An ANSI-saved
        # file still loads (lossily) instead of silently dropping the rules.
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
        if text.strip():
            log.info("Loaded Codex developer instructions from %s", path)
            return text.strip()

    log.warning(
        "No Codex developer instructions found; expected %s or %s",
        DEFAULT_INSTRUCTIONS_FILE,
        HOME_INSTRUCTIONS_FILE,
    )
    return ""


def _safe_worker_report_event_id(metadata: dict[str, Any]) -> str:
    raw_event_id = str(metadata.get("event_id") or "worker-report")
    safe_event_id = "".join(
        ch if ch.isalnum() or ch in "._-" else "-" for ch in raw_event_id
    )
    return safe_event_id[:80] or "worker-report"


def _format_visible_worker_report_prompt(report_text: str) -> str:
    return "\n".join(
        [
            "[BRIDGE/SYSTEM WORKER REPORT TURN]",
            "This is automated bridge/system worker status, not Ben's message.",
            "Do not use tools, inspect files, dispatch workers, approve actions, "
            "ask questions, or start follow-up work.",
            "Reply with one terse assistant-visible status message beginning "
            f"{VISIBLE_REPORT_PREFIX}.",
            "Use only the facts in the report below.",
            "",
            report_text.strip(),
        ]
    )
