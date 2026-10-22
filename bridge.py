#!/usr/bin/env python3
"""Overlord bridge: drive a home-rooted AI "Overlord" from Telegram.

The brain is swappable via ``OVERLORD_BRAIN`` (``claude`` | ``codex``, default
``claude``). Both brains present the same :class:`~modules.brain.Brain`
interface, so this file never needs to know which one is active.

Architecture:

    Telegram (phone)  <-->  TelegramHandler thread  <-->  inbound Queue
                                                              |
                                          asyncio main loop (this file)
                                                              |
                                              Brain (Claude SDK | Codex App Server)
                                                              |
                                       PermissionGate  -->  Telegram choices
                                                            back on the phone

Security:
  * Single-user: TelegramHandler drops every update whose chat_id != OWNER.
  * PermissionGate is the shared second layer for BOTH brains: obvious secrets
    (OFFLIMITS_FRAGMENTS) are auto-denied; anything else that would prompt is
    forwarded to the phone for tap-to-approve, with a timeout that denies.
  * Claude additionally loads ~/.claude/CLAUDE.md + settings.json (deny rules)
    as a hard floor. Codex ignores those, so its guardrails come from its
    sandbox/approval policy + the AGENTS.md in this folder (see README).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Queue
from typing import Any

from modules import startup_state

if __name__ == "__main__":
    # Before the slow imports below, so the splash window appears immediately.
    startup_state.begin(Path(__file__).resolve().parent)

from modules import cli_notify
from modules.brain import Brain, PermissionGate
from modules.host_context import host_instructions
from modules.output_text import OUTPUT_INSTRUCTIONS
from modules.prompt_router import PromptRouter
from modules.permission_audit import PermissionAudit
from modules.gui_settings import decode_paths, PROJECT_FOLDERS, PROJECT_ROOTS, SETTING_NAMES, PERMISSION_LEVEL, permission_level
from modules.codex_discovery import resolve_codex_binary
from modules.commands import (
    HELP_TEXT,
    VALID_BRAINS,
    format_quote,
    format_status,
    format_status_all,
    reset_has_passed,
    set_env_value,
)
from modules.version import display_version
from modules.token_meter import (
    TokenLedger,
    estimate_tokens,
    format_footer,
    format_history,
    normalize_usage,
)
from modules.chat_mirror import (
    ChatMirror,
    ROLE_OWNER,
    ROLE_OVERLORD,
    SOURCE_GUI,
    SOURCE_TELEGRAM,
)
from modules.chat_requests import read_requests
from modules.conversation_history import (
    Handoff,
    SharedConversationHistory,
    add_handoff_to_turn,
)
from modules.telegram_handler import TelegramHandler
from modules.single_instance import AlreadyRunningError, SingleInstance
from modules.windows_tray import WindowsTray
from modules.free_work import FreeWork, normalize_mode
from modules.workers import _ALLOWED_ROOTS, DEFAULT_AIDER_CONTEXT_TOKENS, WorkerManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
# httpx/httpcore log full request URLs at INFO — which include the bot token.
# Keep them quiet so the token never lands in logs/journald.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
log = logging.getLogger("overlord.bridge")
STOP_INTERRUPT_TIMEOUT = 2.0
STOP_CLEANUP_TIMEOUT = 5.0

BASE_DIR = Path(__file__).resolve().parent
CONSOLE_LOG_FILE = BASE_DIR / "run" / "overlord.log"
CONSOLE_STATUS_FILE = BASE_DIR / "run" / "brain-status.json"
# The console is a separate read-only process, so its buttons reach the bridge
# by writing this file; the bridge watches its mtime. One-way and file-based on
# purpose: no socket to secure, and a stale file is simply ignored.
CONSOLE_COMMAND_FILE = BASE_DIR / "run" / "console-command.json"
# Messages typed in the desktop console arrive here. It is an append-only
# queue rather than a single slot, so two quick messages cannot overwrite
# each other on the way to the bridge.
CONSOLE_CHAT_FILE = BASE_DIR / "run" / "console-chat.jsonl"
# The conversation transcript shared with the desktop console: the bridge
# appends every owner message and every reply, and the console reads it.
CHAT_MIRROR_FILE = BASE_DIR / "run" / "chat-mirror.jsonl"
TELEGRAM_CHOICE_INSTRUCTIONS = (
    "When you need the user to choose among discrete options or answer a short "
    "clarifying question, use your native interactive user-input tool instead "
    "of printing a numbered list. Overlord renders that tool as Telegram buttons "
    "and also accepts a typed custom answer. Never request passwords, tokens, "
    "private keys, or other secrets through this Telegram input surface."
)


def configure_file_logging() -> None:
    """Keep a bounded log for the tray's fallback console viewer."""
    try:
        CONSOLE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            CONSOLE_LOG_FILE,
            maxBytes=2 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("Could not enable tray console log: %s", exc)
        return
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    logging.getLogger().addHandler(handler)


configure_file_logging()


def load_env(path: Path) -> None:
    """Minimal .env loader (no external dependency)."""
    if not path.exists():
        return
    # set_env_value() writes UTF-8 (a BOM is tolerated); a hand-edited ANSI file
    # still loads rather than aborting the bridge at import time.
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


def env_first(names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        raw = os.environ.get(name, "").strip()
        if raw:
            return raw
    return default


def env_int_first(names: tuple[str, ...], default: int) -> int:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            continue
        try:
            return int(raw)
        except ValueError:
            log.warning("Invalid %s=%r; trying fallback/default", name, raw)
    return default


def env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    path = Path(raw).expanduser() if raw else default
    return path if path.is_absolute() else BASE_DIR / path

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_RAW = os.environ.get("OWNER_CHAT_ID", "")
CWD = os.environ.get("OVERLORD_CWD", str(Path.home()))
MODEL = os.environ.get("OVERLORD_MODEL", "opus")
# Reasoning effort. Empty means "whatever the engine defaults to" — the bridge
# never invents a level, so an unset value behaves exactly as it did before.
EFFORT = os.environ.get("OVERLORD_EFFORT", "").strip().lower()
INSTRUCTIONS_FILE = os.environ.get("OVERLORD_INSTRUCTIONS_FILE", "").strip()
CLAUDE_AUTO_APPROVE_EDITS = env_bool(
    "OVERLORD_CLAUDE_AUTO_APPROVE_EDITS", False
)
PERMISSION_TIMEOUT = env_int("OVERLORD_PERMISSION_TIMEOUT", 300)
# Auto-approve every action EXCEPT off-limits secrets (which are always denied).
# Trades per-tool Telegram prompts for "just do it".
AUTO_APPROVE = os.environ.get("OVERLORD_AUTO_APPROVE", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
BRAIN = os.environ.get("OVERLORD_BRAIN", "claude").strip().lower()

# Codex-specific (only consulted when BRAIN == "codex").
CODEX_BIN = resolve_codex_binary(os.environ.get("OVERLORD_CODEX_BIN", "codex"))
os.environ["OVERLORD_CODEX_BIN"] = CODEX_BIN
CODEX_MODEL = os.environ.get("OVERLORD_CODEX_MODEL", "")  # "" -> codex default
CODEX_EFFORT = os.environ.get("OVERLORD_CODEX_EFFORT", "").strip().lower()
CODEX_APPROVAL_POLICY = os.environ.get("OVERLORD_CODEX_APPROVAL_POLICY", "on-request")
CODEX_SANDBOX = os.environ.get("OVERLORD_CODEX_SANDBOX", "read-only")
CODEX_APP_SERVER_PROXY = env_bool("OVERLORD_CODEX_APP_SERVER_PROXY", False)
CODEX_APP_SERVER_SOCKET = os.environ.get("OVERLORD_CODEX_APP_SERVER_SOCKET", "")

# Worker report/audit settings. Telegram completion messages remain on; these
# flags only control optional active-conversation context/visibility paths.
WORKER_REPORT_TO_THREAD = env_bool("WORKER_REPORT_TO_THREAD", True)
WORKER_REPORT_VISIBLE_TURN = env_bool("WORKER_REPORT_VISIBLE_TURN", False)
WORKER_REPORT_DIR = env_path("WORKER_REPORT_DIR", BASE_DIR / "worker_reports")
WORKER_REPORT_TAIL_CHARS = max(0, env_int("WORKER_REPORT_TAIL_CHARS", 4000))
WORKER_TELEGRAM_TAIL_CHARS = max(0, env_int("WORKER_TELEGRAM_TAIL_CHARS", 12000))
WORKER_REPORT_EVENTS_MAX_BYTES = max(
    0, env_int("WORKER_REPORT_EVENTS_MAX_BYTES", 1024 * 1024)
)
HANDOFF_CONTEXT_CHARS = max(
    1_000, env_int("OVERLORD_HANDOFF_CONTEXT_CHARS", 12_000)
)
CONTEXT_CHECKPOINT_FILE = env_path(
    "OVERLORD_CONTEXT_CHECKPOINT_FILE", BASE_DIR / "run" / "conversation.json"
)

# Per-prompt token accounting. The footer is the only part that touches every
# reply, so it is the only part with an off switch.
TOKEN_FOOTER = env_bool("OVERLORD_TOKEN_FOOTER", True)
TOKEN_LEDGER_FILE = env_path("OVERLORD_TOKEN_LEDGER_FILE", BASE_DIR / "run" / "token_ledger.json")
TOKEN_LEDGER_MAX = max(10, env_int("OVERLORD_TOKEN_LEDGER_MAX", 200))

# How often the background refresh re-reads provider usage, and how long an
# operator-typed /status will wait for a live reading before falling back to
# the cache. 0 disables the periodic refresh.
STATUS_REFRESH_SECS = max(0, env_int("OVERLORD_STATUS_REFRESH_SECS", 60))
STATUS_REFRESH_TIMEOUT = max(1, env_int("OVERLORD_STATUS_REFRESH_TIMEOUT", 8))

# Live terminal delivery (dual delivery alongside Telegram, brain-neutral —
# see modules/cli_notify.py). CLI_FEED is the durable, always-on, safe path:
# the `overlord` launcher tails this file in a passive tmux pane next to the
# live brain, so reports appear the instant they land, without touching
# anything Ben might be typing. TERMINAL_INJECT is the opt-in, best-effort
# deep path: type the report into the live brain pane as a real turn, but
# only when the pane's prompt line is confirmed idle.
WORKER_REPORT_CLI_FEED = env_bool("WORKER_REPORT_CLI_FEED", True)
WORKER_REPORT_CLI_FEED_PATH = env_path(
    "WORKER_REPORT_CLI_FEED_PATH", WORKER_REPORT_DIR / "cli_feed.log"
)
WORKER_REPORT_TERMINAL_INJECT = env_bool("WORKER_REPORT_TERMINAL_INJECT", False)
WORKER_REPORT_TMUX_SESSION = os.environ.get("WORKER_REPORT_TMUX_SESSION", "").strip()

# Free-model project work (/work): who is asked before a worker writes or runs
# something, how long it waits out rate limits, and how many tool steps it gets.
FREE_WORK_APPROVAL = normalize_mode(os.environ.get("OVERLORD_FREE_WORK_APPROVAL"))
FREE_WORK_PATIENCE = max(0, env_int("OVERLORD_FREE_WORK_PATIENCE", 120))
FREE_WORK_STEPS = max(0, env_int("OVERLORD_FREE_WORK_STEPS", 0))
PROJECTS_ROOT = os.environ.get("OVERLORD_PROJECTS_ROOT", "").strip()

if not TOKEN or not OWNER_RAW:
    startup_state.failed("Configuration", "TELEGRAM_BOT_TOKEN and OWNER_CHAT_ID must be set in .env")
    sys.exit("ERROR: TELEGRAM_BOT_TOKEN and OWNER_CHAT_ID must be set in .env")
OWNER = int(OWNER_RAW)

# Per-brain session files: a Claude session id and a Codex thread id are not
# interchangeable, so each brain keeps its own pinned thread across brain
# switches. Normalize unknown brains to "claude".
_BRAIN_NAME = BRAIN if BRAIN in VALID_BRAINS else "claude"


def project_roots() -> list[Path]:
    """Folders whose children are projects: the configured root, the workspace
    (unless that is the whole home directory) and the standard worker zones."""
    candidates: list[Path] = []
    candidates.extend(configured_paths(PROJECT_ROOTS))
    if PROJECTS_ROOT:
        candidates.append(Path(PROJECTS_ROOT).expanduser())
    workspace = Path(CWD).expanduser()
    try:
        if workspace.resolve() != Path.home().resolve():
            candidates.append(workspace)
    except OSError:
        pass
    candidates.extend(_ALLOWED_ROOTS)
    seen: list[Path] = []
    for root in candidates:
        if root.is_dir() and root not in seen:
            seen.append(root)
    return seen


def worker_extra_roots() -> tuple[Path, ...]:
    """Roots workers may use beyond ~/Projects and ~/Documents (e.g. source/repos)."""
    return tuple(r for r in project_roots() + configured_paths(PROJECT_FOLDERS)
                 if r not in _ALLOWED_ROOTS)


def configured_paths(key: str) -> list[Path]:
    try:
        return decode_paths(os.environ.get(key, ""))
    except (ValueError, OSError, RuntimeError) as exc:
        log.warning("Ignoring invalid %s: %s", key, exc)
        return []


def session_file_for(brain_name: str) -> Path:
    """Return the incompatible, per-brain conversation pin."""
    normalized = brain_name if brain_name in VALID_BRAINS else "claude"
    return BASE_DIR / f".session.{normalized}"


SESSION_FILE = session_file_for(_BRAIN_NAME)
# The `overlord` launcher names its tmux session "overlord-<brain>" to match.
WORKER_REPORT_TMUX_SESSION = WORKER_REPORT_TMUX_SESSION or f"overlord-{_BRAIN_NAME}"
# One-time migration: the original single ".session" held the Claude id.
_LEGACY_SESSION = BASE_DIR / ".session"
_CLAUDE_SESSION_FILE = session_file_for("claude")
if _LEGACY_SESSION.exists() and not _CLAUDE_SESSION_FILE.exists():
    _LEGACY_SESSION.rename(_CLAUDE_SESSION_FILE)


def format_worker_thread_report(report: dict[str, Any]) -> str:
    """Human-readable worker report for active thread context."""
    fields = [
        ("name", report.get("name")),
        ("folder", report.get("folder")),
        ("brain", report.get("brain")),
        ("status", report.get("status")),
        ("session", report.get("session")),
        ("real_codex_session_id", report.get("real_codex_session_id")),
        ("started_at", report.get("started_at")),
        ("finished_at", report.get("finished_at")),
        ("duration_seconds", report.get("duration_seconds")),
        ("exit_code", report.get("exit_code")),
    ]
    lines = [
        "[BRIDGE/SYSTEM WORKER REPORT]",
        "Automated bridge status report. This is not Ben's message. "
        "Use it only as factual context for future worker-status questions.",
    ]
    for key, value in fields:
        if value is not None:
            lines.append(f"{key}: {value}")
    result_tail = str(report.get("result_tail") or "").strip()
    if result_tail:
        lines.extend(["result_tail:", result_tail])
    return "\n".join(lines)


def load_shared_instructions() -> str:
    """Load one canonical instruction file for all supported brains."""
    candidates = []
    if INSTRUCTIONS_FILE:
        candidates.append(Path(INSTRUCTIONS_FILE).expanduser())
    candidates.append(BASE_DIR / "AGENTS.md")
    for path in candidates:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.warning("Could not read shared instructions from %s: %s", path, exc)
            continue
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:  # an ANSI-saved file must not abort startup
            text = data.decode("cp1252", errors="replace")
        if text.strip():
            log.info("Loaded shared brain instructions from %s", path)
            return text.strip()
    return ""


def format_worker_inline_report(report: dict[str, Any]) -> str:
    """Single-line summary safe for tmux ``send-keys -l`` (no embedded newline)."""
    def one_line(value: Any) -> str:
        # Names and folders come from dispatch files, so they can hold newlines;
        # one would submit a partial message when typed into the pane.
        return " ".join(str(value).split())

    name = one_line(report.get("name") or "worker")
    status = one_line(report.get("status") or "unknown")
    duration = report.get("duration_seconds")
    bits = [f"status={status}"]
    if duration is not None:
        bits.append(f"{duration}s")
    folder = report.get("folder")
    if folder:
        bits.append(f"folder={one_line(folder)}")
    return (
        f"[worker report] {name}: {', '.join(bits)} "
        f"(full report: worker_reports/latest/{name}.json)"
    )


def build_brain(gate: PermissionGate, brain_name: str | None = None) -> Brain:
    """Instantiate the configured brain. Default and unknown values -> claude."""
    selected = (brain_name or BRAIN).strip().lower()
    session_file = session_file_for(selected)
    shared_instructions = load_shared_instructions()
    developer_instructions = "\n\n".join(
        part for part in (shared_instructions, TELEGRAM_CHOICE_INSTRUCTIONS, host_instructions(), OUTPUT_INSTRUCTIONS) if part
    )
    if selected == "free":
        from modules.free_brain import FreeBrain, UsageLimiter, DEFAULT_LIMITS, DEFAULT_MODELS, parse_models

        limits = dict(DEFAULT_LIMITS)
        for provider in ("nvidia", "openrouter"):
            rpm_default, day_default = limits[provider]
            limits[provider] = (
                max(0, env_int(f"OVERLORD_FREE_{provider.upper()}_RPM", rpm_default)),
                max(0, env_int(f"OVERLORD_FREE_{provider.upper()}_DAILY", day_default)),
            )
        nvidia_base = env_first(("OVERLORD_WORKER_NVIDIA_API_BASE",))
        return FreeBrain(
            session_file=session_file,
            developer_instructions=shared_instructions,
            models=parse_models(os.environ.get("OVERLORD_FREE_MODELS") or DEFAULT_MODELS),
            model=os.environ.get("OVERLORD_FREE_MODEL", "").strip() or None,
            keys={
                "nvidia": env_first(("OVERLORD_WORKER_NVIDIA_API_KEY", "NVIDIA_API_KEY")),
                "openrouter": env_first(("OVERLORD_FREE_OPENROUTER_API_KEY",
                                         "OVERLORD_WORKER_OPENROUTER_API_KEY")),
            },
            bases={"nvidia": nvidia_base} if nvidia_base else None,
            # A configured OpenRouter key is the consent; set the flag to 0 to opt out.
            openrouter_enabled=env_bool("OVERLORD_FREE_OPENROUTER_ENABLED", True),
            limiter=UsageLimiter(BASE_DIR / "run" / "free_usage.json", limits),
            max_tokens=env_int("OVERLORD_FREE_MAX_TOKENS", 2048),
            history_chars=env_int("OVERLORD_FREE_HISTORY_CHARS", 24_000),
        )

    if selected == "codex":
        # Imported lazily so the Claude path never needs codex deps and vice versa.
        from modules.codex_brain import CodexBrain

        return CodexBrain(
            gate=gate,
            cwd=CWD,
            model=CODEX_MODEL,
            session_file=session_file,
            codex_bin=CODEX_BIN,
            approval_policy=CODEX_APPROVAL_POLICY,
            sandbox=CODEX_SANDBOX,
            app_server_proxy=CODEX_APP_SERVER_PROXY,
            app_server_socket=CODEX_APP_SERVER_SOCKET or None,
            developer_instructions=developer_instructions or None,
            effort=CODEX_EFFORT or None,
        )

    if selected not in ("claude", ""):
        log.warning("Unknown OVERLORD_BRAIN=%r; falling back to 'claude'.", selected)

    from modules.claude_brain import ClaudeBrain

    return ClaudeBrain(
        gate=gate,
        cwd=CWD,
        model=MODEL,
        session_file=session_file,
        developer_instructions=developer_instructions,
        auto_approve_edits=CLAUDE_AUTO_APPROVE_EDITS,
        effort=EFFORT or None,
    )


class Bridge:
    # Class-level default so partially built instances (tests, early failures)
    # report "no active turn" rather than raising.
    _active_turn_task: asyncio.Task[None] | None = None
    _switcher_task: asyncio.Task[None] | None = None
    _free_standby: Any = None  # a free-model pool kept for /work while another brain chats

    def __init__(self) -> None:
        self.prompt_router = PromptRouter.from_environment()
        self.inbound: "Queue[tuple[int, str]]" = Queue()
        self._shutdown_event = asyncio.Event()
        self.gate = PermissionGate(
            telegram=None,  # set right after the handler exists
            owner=OWNER,
            timeout=PERMISSION_TIMEOUT,
            auto_approve=AUTO_APPROVE,
            permission_level=os.environ.get(PERMISSION_LEVEL),
            audit=PermissionAudit(BASE_DIR / "run/permissions.jsonl", root=BASE_DIR),
        )
        self.chat_mirror = ChatMirror(CHAT_MIRROR_FILE)
        self.telegram = TelegramHandler(
            TOKEN,
            self.inbound,
            OWNER,
            on_permission_response=self.gate.on_permission_response,
            on_choice_response=self.gate.on_choice_response,
            on_send=self._mirror_outbound,
        )
        self.gate.telegram = self.telegram
        self.brain_name = _BRAIN_NAME
        self.brain = build_brain(self.gate, self.brain_name)
        self._brain_lock = asyncio.Lock()
        self._active_turn_task: asyncio.Task[None] | None = None
        self._status_cache: dict[str, Any] = self._basic_status()
        self._status_by_brain = {
            name: self._basic_status_for(name) for name in VALID_BRAINS
        }
        self._status_by_brain[self.brain.name] = dict(self._status_cache)
        self._console_status_file = CONSOLE_STATUS_FILE
        self._console_command_file = CONSOLE_COMMAND_FILE
        self._console_command_mtime = 0
        self.tokens = TokenLedger(
            path=TOKEN_LEDGER_FILE, max_entries=TOKEN_LEDGER_MAX
        )
        # Instance-level so a test (or a future /status --fast) can shorten it.
        self._status_timeout: float = STATUS_REFRESH_TIMEOUT
        self._conversation_history = SharedConversationHistory(
            HANDOFF_CONTEXT_CHARS, path=CONTEXT_CHECKPOINT_FILE,
            workspace=str(Path(CWD).resolve()),
        )
        from modules.shared_memory import SharedMemory
        memory_root = (Path(os.environ["LOCALAPPDATA"]) / "Overlord" / "state"
                       if sys.platform == "win32" and os.environ.get("LOCALAPPDATA")
                       else BASE_DIR / "run")
        self.shared_memory = SharedMemory(env_path("OVERLORD_SHARED_MEMORY_FILE", memory_root / "shared-memory.json"))
        from modules.context_pressure import ContextPolicy
        self.context_policy = ContextPolicy(
            env_int("OVERLORD_CONTEXT_WARN_PERCENT", 75),
            env_int("OVERLORD_CONTEXT_COMPACT_PERCENT", 85),
            env_bool("OVERLORD_CONTEXT_AUTO_COMPACT", False),
        )
        self._pending_handoff: Handoff | None = (
            self._conversation_history.handoff_for(self.brain_name)
        )
        self.tray = WindowsTray(
            self.request_shutdown,
            log_path=CONSOLE_LOG_FILE,
            status_path=CONSOLE_STATUS_FILE,
            command_path=CONSOLE_COMMAND_FILE,
            # Windows tray is not responsible for chat requests; ignore.
        )
        self._write_console_status()
        self._thread_report_unsupported_logged = False
        self._visible_report_unsupported_logged = False
        # Brain-agnostic worker dispatch: watches dispatch/ and pushes worker
        # results to the owner on completion (no turn required).
        self.workers = WorkerManager(
            send=self.telegram.send,
            owner=OWNER,
            begin_typing=self.telegram.begin_typing,
            end_typing=self.telegram.end_typing,
            # So a worker killed by a bridge restart is reported as interrupted,
            # not as a failure (a worker that restarts the bridge kills itself:
            # it lives in this service's cgroup).
            is_shutting_down=self._shutdown_event.is_set,
            dispatch_dir=BASE_DIR / "dispatch",
            claude_bin="claude",
            codex_bin=CODEX_BIN,
            claude_model=os.environ.get("OVERLORD_WORKER_MODEL", "sonnet"),
            codex_model=os.environ.get("OVERLORD_WORKER_CODEX_MODEL", "").strip() or None,
            aider_model=env_first(
                ("OVERLORD_WORKER_LOCAL_AGENT_MODEL", "OVERLORD_WORKER_AIDER_MODEL"),
                "openai/Qwen3-Coder-Next",
            ),
            aider_api_base=env_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_API_BASE",
                    "OVERLORD_WORKER_AIDER_API_BASE",
                ),
                "http://127.0.0.1:1234/v1",
            ),
            local_agent_ollama_api_base=env_first(
                ("OVERLORD_WORKER_LOCAL_AGENT_OLLAMA_API_BASE",),
                "http://127.0.0.1:11434/v1",
            ),
            aider_map_tokens=max(
                0,
                env_int_first(
                    (
                        "OVERLORD_WORKER_LOCAL_AGENT_MAP_TOKENS",
                        "OVERLORD_WORKER_AIDER_MAP_TOKENS",
                    ),
                    0,
                ),
            ),
            aider_context_tokens=max(
                2048,
                env_int_first(
                    (
                        "OVERLORD_WORKER_LOCAL_AGENT_CONTEXT_TOKENS",
                        "OVERLORD_WORKER_AIDER_CONTEXT_TOKENS",
                    ),
                    DEFAULT_AIDER_CONTEXT_TOKENS,
                ),
            ),
            aider_min_context_tokens=max(
                1024,
                env_int_first(
                    (
                        "OVERLORD_WORKER_LOCAL_AGENT_MIN_CONTEXT_TOKENS",
                        "OVERLORD_WORKER_AIDER_MIN_CONTEXT_TOKENS",
                    ),
                    2048,
                ),
            ),
            aider_chat_history_tokens=max(
                1024,
                env_int_first(
                    (
                        "OVERLORD_WORKER_LOCAL_AGENT_CHAT_HISTORY_TOKENS",
                        "OVERLORD_WORKER_AIDER_CHAT_HISTORY_TOKENS",
                    ),
                    2048,
                ),
            ),
            aider_keep_alive=env_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_KEEP_ALIVE",
                    "OVERLORD_WORKER_AIDER_KEEP_ALIVE",
                ),
                "0",
            ),
            aider_openai_api_key=env_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_OPENAI_API_KEY",
                    "OVERLORD_WORKER_AIDER_OPENAI_API_KEY",
                ),
                "overlord-local",
            ),
            aider_llamacpp_bin=env_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_BIN",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_BIN",
                ),
                "/tank/ai/llama.cpp/build/bin/llama-server",
            ),
            aider_llamacpp_model=env_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_MODEL",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_MODEL",
                ),
                "/tank/ai/models/Qwen3-Coder-Next-UD-TQ1_0.gguf",
            ),
            aider_llamacpp_hf_repo=env_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_HF_REPO",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_HF_REPO",
                ),
                "unsloth/Qwen3-Coder-Next-GGUF:UD-TQ1_0",
            ),
            aider_llamacpp_host=env_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_HOST",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_HOST",
                ),
                "127.0.0.1",
            ),
            aider_llamacpp_port=env_int_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_PORT",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_PORT",
                ),
                1234,
            ),
            aider_llamacpp_threads=env_int_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_THREADS",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_THREADS",
                ),
                16,
            ),
            aider_llamacpp_batch=env_int_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_BATCH",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_BATCH",
                ),
                1024,
            ),
            aider_llamacpp_n_cpu_moe=env_int_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_N_CPU_MOE",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_N_CPU_MOE",
                ),
                36,
            ),
            aider_llamacpp_cache_type_k=env_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_CACHE_TYPE_K",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_CACHE_TYPE_K",
                ),
                "q8_0",
            ),
            aider_llamacpp_cache_type_v=env_first(
                (
                    "OVERLORD_WORKER_LOCAL_AGENT_LLAMACPP_CACHE_TYPE_V",
                    "OVERLORD_WORKER_AIDER_LLAMACPP_CACHE_TYPE_V",
                ),
                "q8_0",
            ),
            nvidia_model=env_first(("OVERLORD_WORKER_NVIDIA_MODEL",), ""),
            nvidia_api_base=env_first(("OVERLORD_WORKER_NVIDIA_API_BASE",), ""),
            nvidia_api_key=env_first(
                ("OVERLORD_WORKER_NVIDIA_API_KEY", "NVIDIA_API_KEY"), ""
            ),
            free_completer=lambda messages, tools: self.free_work.complete(messages, tools),
            tool_approver=lambda folder, tool, request: self.free_work.approve(folder, tool, request),
            extra_roots=worker_extra_roots(),
            free_max_steps=FREE_WORK_STEPS,
            report_dir=WORKER_REPORT_DIR,
            report_tail_chars=WORKER_REPORT_TAIL_CHARS,
            telegram_tail_chars=WORKER_TELEGRAM_TAIL_CHARS,
            report_events_max_bytes=WORKER_REPORT_EVENTS_MAX_BYTES,
            on_report=self._handle_worker_report,
        )
        self.free_work = FreeWork(
            send=self.telegram.send, roots=project_roots, workers=self.workers,
            gate=self.gate, pool=self._free_pool,
            approval=FREE_WORK_APPROVAL, patience=FREE_WORK_PATIENCE,
            response_tokens=env_int("OVERLORD_FREE_WORK_MAX_TOKENS", 8192),
            projects=lambda: configured_paths(PROJECT_FOLDERS),
        )

    # ---------------------------------------------------------------- main loop
    async def run(self) -> None:
        startup_state.report("Connecting to Telegram")
        self.telegram.start()
        if not self.telegram.wait_ready(30):
            log.error("Telegram handler failed to start within 30s")
            startup_state.failed("Telegram", "Telegram did not connect within 30s. Check the bot token and network.")
            return

        resumed = session_file_for(self.brain_name).exists()
        startup_state.report(f"Starting the {self.brain.name} brain")
        try:
            await self.brain.connect()
        except Exception as exc:
            log.exception("Brain failed to start")
            self.telegram.send(OWNER, f"⚠️ Failed to start {self.brain.name}: {exc}")
            startup_state.failed(f"{self.brain.name} brain", f"Failed to start {self.brain.name}: {exc}")
            return

        asyncio.create_task(self._refresh_status(self.brain))

        log.info(
            "Overlord %s online (brain=%s, cwd=%s, resumed=%s, permission_level=%s)",
            display_version(),
            self.brain.name,
            CWD,
            resumed,
            self.gate.permission_level,
        )
        self.tray.start(self.brain.name)
        self._chat_request_path = CONSOLE_CHAT_FILE
        approve_note = f"\nPermission level: {self.gate.permission_level}."
        if self._conversation_history.persistence_note:
            approve_note += "\n⚠️ " + self._conversation_history.persistence_note
        version = display_version()
        self.telegram.send(
            OWNER,
            (
                f"🟢 Overlord {version} online [{self.brain.name}] — picked up "
                "where we left off. (/new for a clean slate.)"
                if resumed
                else f"🟢 Overlord {version} online [{self.brain.name}]. Send me a "
                "task. (/new starts a clean session.)"
            )
            + approve_note,
        )
        startup_state.ready()
        # Start the brain-agnostic worker dispatch watcher (background).
        asyncio.create_task(self.workers.watch())
        if STATUS_REFRESH_SECS:
            asyncio.create_task(self._status_refresh_loop())
        asyncio.create_task(self._console_command_loop())
        try:
            while not self._shutdown_event.is_set():
                chat_id, text = await asyncio.get_running_loop().run_in_executor(
                    None, self._inbound_get_with_shutdown
                )
                if chat_id is None:
                    break
                await self._dispatch_inbound(chat_id, text)
        finally:
            if self._turn_is_active():
                await self._stop_active_turn()
            await self.brain.disconnect()
            self.tray.stop()

    async def _dispatch_inbound(
        self, chat_id: int, text: str, *, source: str = SOURCE_TELEGRAM
    ) -> None:
        """Route one owner message to its command handler or start a turn.

        Handlers run on the main loop, so one that raises must not unwind it:
        that would shut the whole bridge down over a single bad command.

        *source* says where the message came from ("telegram" or "gui"), so
        the shared transcript can show where each message was typed.
        """
        self.chat_mirror.append(ROLE_OWNER, text, source=source)
        stripped = text.strip()
        if not stripped:
            return
        command = stripped.lower().split(maxsplit=1)[0]
        try:
            if command == "/new":
                await self._reset_session(chat_id)
            elif command == "/help":
                self.telegram.send(chat_id, HELP_TEXT)
            elif command == "/status":
                await self._handle_status(chat_id, text)
            elif command == "/stop":
                await self._handle_stop(chat_id)
            elif command == "/steer":
                await self._handle_steer(chat_id, text)
            elif command == "/brain":
                await self._handle_brain(chat_id, text)
            elif command == "/tokens":
                self._handle_tokens(chat_id, text)
            elif command == "/quote":
                await self._handle_quote(chat_id, text)
            elif command == "/model":
                await self._handle_model(chat_id, text)
            elif command == "/effort":
                await self._handle_effort(chat_id, text)
            elif command == "/permissions":
                self._handle_permissions(chat_id, text)
            elif command == "/context":
                self._handle_context(chat_id)
            elif command == "/work":
                await self.free_work.handle(chat_id, text)
            elif command == "/compact":
                self._start_compaction(chat_id)
            else:
                self._start_turn(chat_id, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the bridge alive
            log.exception("Command %r failed", command)
            self.telegram.send(chat_id, f"⚠️ {command or 'Message'} failed: {exc}")

    def _mirror_outbound(self, chat_id: int, text: str) -> None:
        """Record an outbound reply so the console can mirror the chat."""
        self.chat_mirror.append(ROLE_OVERLORD, text, source=SOURCE_TELEGRAM)

    async def _free_pool(self):
        """The free-model pool workers draw from: the active free brain, else a
        standby one (it shares the persisted usage limits either way)."""
        if self.brain.name == "free":
            return self.brain
        if self._free_standby is None:
            standby = build_brain(self.gate, "free")
            await standby.connect()
            self._free_standby = standby
        return self._free_standby

    def _inbound_get_with_shutdown(self) -> tuple[int | None, str | None]:
        if self._shutdown_event.is_set():
            return None, None
        item = self.inbound.get()
        if self._shutdown_event.is_set():
            return None, None
        return item

    def request_shutdown(self) -> None:
        self._shutdown_event.set()
        self.inbound.put((-1, ""))

    async def _handle_worker_report(self, report: dict[str, Any]) -> None:
        memory = getattr(self, "shared_memory", None)
        if memory is not None:
            try:
                memory.remember_worker(report)
            except (ValueError, OSError) as exc:
                log.warning("Could not save shared worker memory: %s", exc)
        if not any(
            (
                WORKER_REPORT_TO_THREAD,
                WORKER_REPORT_VISIBLE_TURN,
                WORKER_REPORT_CLI_FEED,
                WORKER_REPORT_TERMINAL_INJECT,
            )
        ):
            return
        text = format_worker_thread_report(report)

        if WORKER_REPORT_TO_THREAD or WORKER_REPORT_VISIBLE_TURN:
            await self._record_worker_report_in_brain(report, text)

        # Live terminal delivery: independent of the brain-context paths above
        # (no self._brain_lock — this never touches self.brain, only the
        # terminal's own tmux pane), so it never waits on an in-flight turn.
        await self._deliver_worker_report_to_terminal(report, text)

    async def _record_worker_report_in_brain(
        self, report: dict[str, Any], text: str
    ) -> None:
        recorded: bool | None = None
        visible: bool | None = None
        async with self._brain_lock:
            if WORKER_REPORT_TO_THREAD:
                try:
                    recorded = await self.brain.record_event(text, metadata=report)
                except Exception as exc:  # noqa: BLE001 - optional report path
                    log.warning("Worker report thread append failed: %s", exc)
                    recorded = False
            if WORKER_REPORT_VISIBLE_TURN:
                try:
                    visible = await self.brain.record_visible_event(
                        text, metadata=report
                    )
                except Exception as exc:  # noqa: BLE001 - optional report path
                    log.warning("Worker report visible turn failed: %s", exc)
                    visible = False

        if recorded is True:
            log.info(
                "Recorded worker report in active %s thread: %s/%s",
                self.brain.name,
                report.get("name"),
                report.get("status"),
            )
        elif WORKER_REPORT_TO_THREAD and not self._thread_report_unsupported_logged:
            self._thread_report_unsupported_logged = True
            log.info(
                "Worker report thread append is unsupported for brain=%s; "
                "using Telegram plus %s",
                self.brain.name,
                WORKER_REPORT_DIR,
            )
        if visible is True:
            log.info(
                "Started visible worker report turn in active %s thread: %s/%s",
                self.brain.name,
                report.get("name"),
                report.get("status"),
            )
        elif WORKER_REPORT_VISIBLE_TURN and not self._visible_report_unsupported_logged:
            self._visible_report_unsupported_logged = True
            log.info(
                "Visible worker report turns are unsupported for brain=%s; "
                "using Telegram plus %s",
                self.brain.name,
                WORKER_REPORT_DIR,
            )

    async def _deliver_worker_report_to_terminal(
        self, report: dict[str, Any], text: str
    ) -> None:
        """Push the report into the live terminal Overlord (see modules/cli_notify.py).

        CLI_FEED (default on) is durable and safe: append to a feed file that
        the `overlord` launcher tails in a passive tmux pane, so it appears in
        the live terminal without ever touching Ben's input. TERMINAL_INJECT
        (default off) is opt-in, best-effort deep injection: type the report
        into the live brain pane as a real turn, only when that pane's prompt
        line is confirmed idle.
        """
        loop = asyncio.get_running_loop()
        if WORKER_REPORT_CLI_FEED:
            try:
                await loop.run_in_executor(
                    None, cli_notify.append_feed, WORKER_REPORT_CLI_FEED_PATH, text
                )
            except OSError as exc:
                log.warning("Worker report CLI feed append failed: %s", exc)

        if not WORKER_REPORT_TERMINAL_INJECT:
            return
        session = WORKER_REPORT_TMUX_SESSION
        exists = await loop.run_in_executor(
            None, cli_notify.tmux_session_exists, session
        )
        if not exists:
            log.debug(
                "Terminal inject skipped for %s; no live tmux session %s",
                report.get("name"),
                session,
            )
            return
        idle = await loop.run_in_executor(None, cli_notify.pane_input_is_idle, session)
        if not idle:
            log.info(
                "Terminal inject skipped for %s (tmux session %s not confirmed idle)",
                report.get("name"),
                session,
            )
            return
        inline = format_worker_inline_report(report)
        injected = await loop.run_in_executor(
            None, cli_notify.inject_turn, session, inline
        )
        if injected:
            log.info(
                "Injected worker report into live tmux session %s: %s/%s",
                session,
                report.get("name"),
                report.get("status"),
            )
        else:
            log.warning("Terminal inject failed for tmux session %s", session)

    async def _reset_session(self, chat_id: int) -> None:
        await self._stop_active_turn()
        if self._turn_is_active():
            self.telegram.send(chat_id, "Session reset is waiting for the active operation to finish cleanup.")
            return
        try:
            async with self._brain_lock:
                await self.brain.reset()
                self._conversation_history.clear()
                self._conversation_history.mark_seen(self.brain.name)
                self._pending_handoff = None
                # "Session tokens" in /status means this conversation, so a
                # clean slate starts the tally over too.
                self.tokens.clear()
                if hasattr(self, "gate"):
                    self.gate.revoke_grants()
        except Exception as exc:
            log.exception("Brain reset failed")
            self.telegram.send(chat_id, f"⚠️ Could not reset session: {exc}")
            return
        self.telegram.send(
            chat_id, "🆕 Fresh session started — previous context cleared."
        )
        log.info("Session reset via /new")

    def _handle_permissions(self, chat_id: int, text: str) -> None:
        parts = text.split()
        if len(parts) == 1:
            self.telegram.send(chat_id, self.gate.format_grants())
        elif len(parts) == 3 and parts[1].lower() == "level" and parts[2].lower() in {"ask", "safe"}:
            self.gate.revoke_grants()
            self.gate.permission_level = parts[2].lower()
            self.telegram.send(chat_id, f"Permission level: {self.gate.permission_level}. "
                               "Previous grants and timed access cleared. Settings saves the startup level.")
        elif len(parts) == 3 and parts[1].lower() == "safe" and parts[2].lower() in {"on", "off"}:
            self.gate.safe_commands = parts[2].lower() == "on"
            self.telegram.send(chat_id, f"Routine command auto-approval: {parts[2].lower()}.")
        elif len(parts) in (2, 3) and parts[1].lower() == "full":
            try:
                minutes = int(parts[2].lower().removesuffix("m")) if len(parts) == 3 else 10
                granted = self.gate.grant_full_access(minutes)
            except ValueError:
                self.telegram.send(chat_id, "Use /permissions full <minutes> (1–1440; default 10).")
                return
            if granted:
                self.telegram.send(chat_id,
                    f"Full access enabled for {minutes} minutes for bridge approval requests, "
                    "including workers. It expires automatically; /permissions revoke all ends it early. "
                    "Off-limits protections still apply. Already started commands may finish after expiry.")
        elif len(parts) == 3 and parts[1].lower() == "revoke":
            count = self.gate.revoke_grants(
                None if parts[2].lower() == "all" else parts[2]
            )
            self.telegram.send(chat_id, f"Revoked {count} permission grants.")
        else:
            self.telegram.send(chat_id, "Usage: /permissions [level <ask|safe> | full [minutes] | safe <on|off> | revoke <id|all>]")

    def _handle_context(self, chat_id: int) -> None:
        text = f"Context [{self.brain.name}]"
        tokens = self._status_cache.get("tokens") or {}
        window = tokens.get("modelContextWindow")
        from modules.context_pressure import snapshot_for, describe
        snapshot = snapshot_for(self.brain)
        if snapshot:
            text += f"\nLast context snapshot: {describe(snapshot)}\nObserved: {snapshot['observed_at']}"
        else:
            text += "\nContext size: unknown (no fresh reading for this session/model)."
        prompt_tokens = getattr(self.brain, "last_prompt_tokens", None)
        if type(prompt_tokens) is int:
            text += f"\nLast conversation request: {prompt_tokens:,} input tokens (before reply/editing)"
        policy = getattr(self, "context_policy", None)
        if policy:
            text += (f"\nWarning: {policy.warn}% · Automatic compaction: "
                     + (f"{policy.compact}%" if policy.automatic else "off"))
        text += f"\nCompaction: {getattr(self.brain, 'compaction_status', 'unknown')}"
        details = self._conversation_history.status()
        details += (f"\nModel context window: {window:,} tokens" if isinstance(window, int)
                    else "\nModel context window: unknown")
        text += f"\n```log\n{details}\n```"
        self.telegram.send(chat_id, text)

    async def _manage_context(self, chat_id: int) -> None:
        from modules.context_pressure import snapshot_for, describe
        policy = getattr(self, "context_policy", None)
        if policy is None or self.gate.pending or self.gate.choice_pending:
            return
        snapshot = snapshot_for(self.brain)
        if snapshot is None:
            return
        action = policy.action(self.brain, snapshot)
        if action == "warn":
            self.telegram.send(chat_id, f"⚠️ Context is growing: {describe(snapshot)}. "
                               + (f"Automatic compaction at {policy.compact}%." if policy.automatic
                                  else "Use /compact to reduce it."))
        elif action == "compact":
            await self._handle_compaction(chat_id, reason=f"Automatic threshold: {describe(snapshot)}")

    def _start_compaction(self, chat_id: int) -> None:
        if self._turn_is_active() or self.gate.pending or self.gate.choice_pending:
            self.telegram.send(chat_id, "Finish or stop the active operation before compacting.")
            return
        self._active_turn_task = asyncio.create_task(self._handle_compaction(chat_id))

    async def _handle_compaction(self, chat_id: int, *, reason: str = "") -> None:
        outcome = "ok"
        started = False
        self.telegram.begin_typing(chat_id)
        try:
            async with self._brain_lock:
                if self.gate.pending or self.gate.choice_pending:
                    self.telegram.send(chat_id, "Compaction deferred while an approval or question is pending.")
                    return
                if not self._conversation_history.checkpoint():
                    self.telegram.send(chat_id, "Compaction not started: checkpoint save failed.")
                    return
                self.telegram.send(chat_id, "Compacting the conversation…" + (f"\n{reason}" if reason else ""))
                started = True
                error = await self.brain.compact()
                if error:
                    outcome = "error"
                    self.telegram.send(chat_id, f"⚠️ {error}")
                else:
                    self.telegram.send(chat_id, "Conversation compacted; session and grants preserved.")
        except asyncio.CancelledError:
            outcome = "stopped"
            raise
        except Exception as exc:
            outcome = "error"
            self.telegram.send(chat_id, f"⚠️ Compaction did not complete: {exc}")
        finally:
            if started:
                self._record_turn_tokens(chat_id, "/compact", outcome=outcome)
            self.telegram.end_typing(chat_id)

    async def _handle_status(self, chat_id: int, text: str = "/status") -> None:
        """Answer /status with a reading taken NOW, not the previous one.

        This used to send ``self._status_cache`` and only afterwards kick off a
        refresh, so every /status showed the state as of the *previous* /status
        — permanently one command stale, and stale by however long ago that was.
        Now the refresh is awaited first, bounded by STATUS_REFRESH_TIMEOUT so a
        slow or offline provider degrades to the cached reading instead of
        hanging the command, and the reading's age is printed either way.
        """
        timeout = getattr(self, "_status_timeout", STATUS_REFRESH_TIMEOUT)
        try:
            await asyncio.wait_for(
                self._refresh_status(self.brain, force=True), timeout=timeout
            )
        except asyncio.TimeoutError:
            log.info("/status refresh exceeded %ss; using the cached reading.", timeout)

        status = dict(
            self._status_cache
            if self._status_cache.get("brain") == self.brain.name
            else self._basic_status()
        )
        status["brain"] = self.brain.name
        status["model"] = getattr(self.brain, "model", None) or status.get("model")
        status["effort"] = getattr(self.brain, "effort", None) or status.get("effort")
        status["session_id"] = getattr(self.brain, "session_id", None)
        status["turn_state"] = "active" if self._turn_is_active() else "idle"
        if hasattr(self, "_status_by_brain"):
            self._status_by_brain[self.brain.name] = dict(status)
        self._write_console_status()
        # Attached after the per-brain snapshot above: the ledger is a live
        # object, not serialisable state for the tray's status file.
        status["ledger"] = getattr(self, "tokens", None)

        argument = (text or "").strip().split(maxsplit=1)
        if len(argument) > 1 and argument[1].strip().lower() in ("all", "*", "brains"):
            statuses = {
                name: dict(getattr(self, "_status_by_brain", {}).get(name) or {})
                or self._basic_status_for(name)
                for name in VALID_BRAINS
            }
            statuses[self.brain.name] = status
            self.telegram.send(
                chat_id, format_status_all(statuses, self.brain.name)
            )
            return
        self.telegram.send(chat_id, format_status(status))

    async def _console_command_loop(self) -> None:
        # Ignore whatever is already on disk from a previous run.
        try:
            self._console_command_mtime = self._console_command_file.stat().st_mtime_ns
        except OSError:
            self._console_command_mtime = 0
        while not self._shutdown_event.is_set():
            await asyncio.sleep(0.4)
            try:
                mtime = self._console_command_file.stat().st_mtime_ns
                if mtime == self._console_command_mtime:
                    continue
                self._console_command_mtime = mtime
                payload = json.loads(
                    self._console_command_file.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, TypeError):
                continue
            action = str((payload or {}).get("action") or "").strip().lower()
            try:
                await self._run_console_action(action, payload if isinstance(payload, dict) else {})
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a button must not kill the loop
                log.warning("Console action %r failed: %s", action, exc)

    # Settings the setup window may change while the bridge is running.
    _RELOADABLE_ENV = (
        "OVERLORD_FREE_", "OVERLORD_WORKER_NVIDIA_", "OVERLORD_WORKER_OPENROUTER_",
        "NVIDIA_API_KEY",
    )

    async def _reload_env(self) -> None:
        """Apply API-key, project, and approval edits without a restart."""
        env_file = BASE_DIR / ".env"
        try:
            data = env_file.read_bytes()
        except OSError:
            return
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
        wanted: dict[str, str] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith(self._RELOADABLE_ENV) or key in SETTING_NAMES:
                wanted[key] = value.strip().strip('"').strip("'")
        # Only what the file says is applied (a cleared key is written as an empty
        # value); settings that come from the process environment are left alone.
        os.environ.update(wanted)
        global PROJECTS_ROOT, AUTO_APPROVE, CLAUDE_AUTO_APPROVE_EDITS, FREE_WORK_APPROVAL
        PROJECTS_ROOT = os.environ.get("OVERLORD_PROJECTS_ROOT", PROJECTS_ROOT).strip()
        AUTO_APPROVE = env_bool("OVERLORD_AUTO_APPROVE", AUTO_APPROVE)
        CLAUDE_AUTO_APPROVE_EDITS = env_bool("OVERLORD_CLAUDE_AUTO_APPROVE_EDITS", CLAUDE_AUTO_APPROVE_EDITS)
        FREE_WORK_APPROVAL = normalize_mode(os.environ.get("OVERLORD_FREE_WORK_APPROVAL"))
        if self.gate is not None:
            selected_level = permission_level(os.environ.get(PERMISSION_LEVEL), legacy_auto=AUTO_APPROVE)
            if selected_level != self.gate.permission_level:
                self.gate.revoke_grants()
            self.gate.permission_level = selected_level
        if self.brain.name == "claude":
            self.brain.auto_approve_edits = CLAUDE_AUTO_APPROVE_EDITS
        if hasattr(self, "workers"):
            self.workers.extra_roots = worker_extra_roots()
        if hasattr(self, "free_work"):
            self.free_work.approval = FREE_WORK_APPROVAL
        self._free_standby = None  # rebuilt with the new keys on next use
        log.info("Reloaded %d setting(s) from .env", len(wanted))
        if self.brain.name == "free" and not self._turn_is_active():
            candidate = build_brain(self.gate, "free")
            async with self._brain_lock:
                await candidate.connect()
                previous, self.brain = self.brain, candidate
                await previous.disconnect()
            self._status_by_brain["free"] = self._basic_status_for("free")
            self._status_cache = dict(self._status_by_brain["free"])
        else:
            self._status_by_brain["free"] = self._basic_status_for("free")
        self._write_console_status()
        self.telegram.send(OWNER, "🔑 Settings reloaded from the setup window.")

    async def _run_console_action(self, action: str, payload: dict | None = None) -> None:
        """Perform one console action.

        *payload* is the whole console command file, so an action that carries
        content (a chat message typed in the window) can read it. The action
        name alone stays supported for the plain button presses.
        """
        if action == "shutdown":
            log.info("Stop requested from the console")
            self.request_shutdown()
        elif action == "refresh_status":
            await self._refresh_status(self.brain, force=True)
            self._write_console_status()
            log.info("Refreshed %s status from the console", self.brain.name)
        elif action == "refresh_all":
            # Only the active brain can be read live; the others are re-read
            # from their on-disk usage caches, which is what /status all shows.
            await self._refresh_status(self.brain, force=True)
            for name in VALID_BRAINS:
                if name == self.brain.name:
                    continue
                self._status_by_brain[name] = self._basic_status_for(name)
            self._write_console_status()
            log.info("Refreshed all brain status cards from the console")
        elif action == "reload_env":
            await self._reload_env()
        elif action == "send_status":
            await self._handle_status(OWNER, "/status")
            log.info("Sent /status to Telegram from the console")
        elif action == "send_status_all":
            await self._handle_status(OWNER, "/status all")
            log.info("Sent /status all to Telegram from the console")
        elif action == "chat":
            await self._handle_gui_chat(payload or {})
        else:
            log.debug("Ignoring unknown console action %r", action)

    async def _handle_gui_chat(self, payload: dict) -> None:
        """Take one message typed in the desktop console as an owner message.

        It goes through exactly the same door as a Telegram message — same
        commands, same turn handling — and is then echoed to Telegram so the
        phone shows the same conversation the window shows.
        """
        text = str((payload or {}).get("text") or "").strip()
        if not text:
            log.debug("Ignoring an empty console chat message")
            return
        log.info("Message from the desktop console: %s", text)
        # The echo to the phone is not mirrored again: _dispatch_inbound below
        # records this message once, as the owner's message from the window.
        self.telegram.send(OWNER, f"🖥️ {text}", mirror=False)
        await self._dispatch_inbound(OWNER, text, source=SOURCE_GUI)

    async def _status_refresh_loop(self) -> None:
        """Keep the cached reading warm so the tray and console stay current."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(STATUS_REFRESH_SECS)
                if self._turn_is_active():
                    # A turn holds the brain lock and, for Codex, the same
                    # JSON-RPC channel a rate-limit read would use. Skip this
                    # tick rather than queue behind a long answer.
                    continue
                await self._refresh_status(self.brain)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a refresh must never stop the bridge
                log.debug("Periodic status refresh failed: %s", exc)

    def _basic_status(self) -> dict[str, Any]:
        return self._basic_status_for(self.brain.name)

    def _basic_status_for(self, brain_name: str) -> dict[str, Any]:
        if brain_name == getattr(self.brain, "name", None):
            model = getattr(self.brain, "model", None) or "default"
            effort = getattr(self.brain, "effort", None)
            session_id = getattr(self.brain, "session_id", None)
        else:
            if brain_name == "free":
                model = os.environ.get("OVERLORD_FREE_MODEL", "").strip() or "default"
                effort = None
            else:
                model = MODEL if brain_name == "claude" else (CODEX_MODEL or "default")
                effort = EFFORT if brain_name == "claude" else CODEX_EFFORT
            session_id = "saved" if session_file_for(brain_name).exists() else None
        status = {
            "brain": brain_name,
            "model": model,
            "effort": effort or None,
            "session_id": session_id,
            "usage": self._read_cached_usage(brain_name),
        }
        if brain_name == "free":
            # The free brain has no plan window: describe keys, models and budgets.
            holder = self.brain if brain_name == getattr(self.brain, "name", None) else None
            try:
                holder = holder or build_brain(None, "free")
                status.update(holder.status_snapshot())
                status["session_id"] = session_id
            except Exception as exc:  # noqa: BLE001 - status is best effort
                log.debug("Could not describe the free brain: %s", exc)
        return status

    @staticmethod
    def _read_cached_usage(brain_name: str) -> dict[str, Any] | None:
        if brain_name not in ("claude", "codex"):
            return None
        if brain_name == "codex":
            path = Path.home() / ".cache" / "overlord" / "codex_usage.json"
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else None
            except (OSError, ValueError, TypeError):
                return None

        path = Path.home() / ".cache" / "near-limit-handoff" / "usage.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(value, dict):
            return None

        def window(key: str) -> dict[str, Any] | None:
            source = value.get(key)
            if not isinstance(source, dict):
                return None
            try:
                used = round(float(source["utilization"]), 1)
            except (KeyError, TypeError, ValueError):
                return None
            resets_at = source.get("resets_at")
            passed = reset_has_passed(resets_at)
            if passed:
                used = 0.0  # rolled over since the cache was written
            return {
                "used": used,
                "gas": max(0, round(100 - used, 1)),
                "resets_at": resets_at,
                "reset_passed": passed,
            }

        session = window("five_hour")
        weekly = window("seven_day")
        if session is None and weekly is None:
            return None
        return {"session": session, "weekly": weekly, "source": "cache"}

    def _write_console_status(self) -> None:
        path = getattr(self, "_console_status_file", None)
        if path is None:
            return
        statuses = {
            name: dict(status)
            for name, status in getattr(self, "_status_by_brain", {}).items()
        }
        active_status = statuses.get(self.brain.name)
        if active_status is not None:
            active_status["turn_state"] = (
                "active" if self._turn_is_active() else "idle"
            )
        payload = {
            "version": display_version(),
            "active_brain": self.brain.name,
            "brains": statuses,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            log.debug("Could not update tray brain status: %s", exc)

    async def _refresh_status(self, brain: Brain, *, force: bool = False) -> None:
        try:
            try:
                status = await brain.status(force_refresh=force)
            except TypeError as exc:
                # A brain (or a test double) that predates the keyword still works.
                if "force_refresh" not in str(exc):
                    raise
                status = await brain.status()
        except Exception as exc:  # noqa: BLE001 - status must not stop the bridge
            log.warning("Background status refresh failed: %s", exc)
            return

        status.setdefault("checked_at", time.time())
        if brain is self.brain:
            self._status_cache = status
            if hasattr(self, "_status_by_brain"):
                self._status_by_brain[brain.name] = dict(status)
            self._write_console_status()

    def _turn_is_active(self) -> bool:
        return self._active_turn_task is not None and not self._active_turn_task.done()

    def _start_turn(self, chat_id: int, text: str) -> bool:
        if self._turn_is_active():
            self.telegram.send(
                chat_id,
                "⏳ A turn is already active. Use /steer <message> to redirect it "
                "or /stop to cancel it.",
            )
            return False
        self._active_turn_task = asyncio.create_task(self._handle_turn(chat_id, text))
        self._write_console_status()
        self._active_turn_task.add_done_callback(
            lambda _task: self._write_console_status()
        )
        return True

    async def _stop_active_turn(self) -> bool:
        task = self._active_turn_task
        if task is None or task.done():
            return False
        try:
            async with asyncio.timeout(STOP_INTERRUPT_TIMEOUT):
                interrupted = await self.brain.interrupt_active_turn()
        except Exception:
            interrupted = False
        if not interrupted:
            task.cancel()
        done, pending = await asyncio.wait({task}, timeout=STOP_CLEANUP_TIMEOUT)
        if pending:
            task.cancel()
            done, pending = await asyncio.wait({task}, timeout=STOP_CLEANUP_TIMEOUT)
        if done and not task.cancelled():
            task.exception()  # retrieve a finished task's failure
        return not pending

    async def _handle_stop(self, chat_id: int) -> None:
        running = getattr(getattr(self, "workers", None), "_running", {})
        workers = {name: task for name, task in list(running.items()) if not task.done()}
        active_turn = self._turn_is_active()
        if not active_turn and not workers:
            self.telegram.send(chat_id, "Nothing is running.")
            return
        # Cancel workers first: one may be waiting on an approval that otherwise
        # stays live after the foreground chat turn has already returned.
        for task in workers.values():
            task.cancel()
        if workers:
            self.telegram.send(chat_id, "⏹️ Stopping workers: " + ", ".join(workers))
        if active_turn:
            self.telegram.send(chat_id, "⏹️ Stopping the active turn…")
            await self._stop_active_turn()
        pending = set()
        if workers:
            done, pending = await asyncio.wait(set(workers.values()), timeout=STOP_CLEANUP_TIMEOUT)
            for task in done:
                if not task.cancelled():
                    task.exception()
            for name, task in workers.items():
                if task.done() and running.get(name) is task:
                    running.pop(name, None)
        if self._turn_is_active() or pending:
            self.telegram.send(chat_id, "Cancellation requested; operation cleanup is still pending.")
        elif workers:
            self.telegram.send(chat_id, "Workers stopped.")

    async def _handle_steer(self, chat_id: int, text: str) -> None:
        parts = text.strip().split(maxsplit=1)
        if len(parts) == 1 or not parts[1].strip():
            self.telegram.send(chat_id, "Usage: /steer <new guidance>")
            return
        if self._turn_is_active():
            self.telegram.send(chat_id, "↪️ Steering the active turn…")
        await self._stop_active_turn()
        if self._turn_is_active():
            self.telegram.send(chat_id, "Steering is waiting for the previous operation to finish cleanup.")
            return
        self._start_turn(chat_id, parts[1].strip())

    def _handle_tokens(self, chat_id: int, text: str) -> None:
        parts = text.strip().split(maxsplit=1)
        limit = 10
        if len(parts) > 1:
            try:
                limit = max(1, min(50, int(parts[1].strip())))
            except ValueError:
                self.telegram.send(chat_id, "Usage: /tokens [how many, 1-50]")
                return
        self.telegram.send(chat_id, format_history(self.tokens, limit))

    async def _handle_quote(self, chat_id: int, text: str) -> None:
        """Price a prompt before sending it — no turn, no context change."""
        parts = text.strip().split(maxsplit=1)
        if len(parts) == 1 or not parts[1].strip():
            self.telegram.send(
                chat_id,
                "Usage: /quote <the prompt you're thinking of sending>\n"
                "Counts its input tokens without sending it.",
            )
            return
        prompt = parts[1].strip()
        try:
            count, source = await self.brain.count_input_tokens(prompt)
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail
            log.warning("Token count failed (%s); using the local estimate.", exc)
            count, source = estimate_tokens(prompt), "estimate"
        if count is None:
            count, source = estimate_tokens(prompt), "estimate"

        # Anything queued for the next turn is charged with it, so quote the
        # real bill: a pending brain-switch handoff is prepended to whatever
        # the operator sends next.
        context_tokens: int | None = None
        if self._pending_handoff is not None:
            context_tokens = estimate_tokens(self._pending_handoff.text)

        self.telegram.send(
            chat_id,
            format_quote(
                prompt_tokens=count,
                source=source,
                context_tokens=context_tokens,
                model=getattr(self.brain, "model", None) or "default",
                brain=self.brain.name,
            ),
        )

    async def _handle_model(self, chat_id: int, text: str) -> None:
        await self._handle_engine_setting(chat_id, text, kind="model")

    async def _handle_effort(self, chat_id: int, text: str) -> None:
        await self._handle_engine_setting(chat_id, text, kind="effort")

    async def _handle_engine_setting(
        self, chat_id: int, text: str, *, kind: str
    ) -> None:
        """Shared body for /model and /effort.

        Both are the same operation on a different field: show the current
        value with no argument, otherwise ask the brain to apply the new one
        and persist it to .env under the key that belongs to THIS brain, so a
        Claude model never overwrites the Codex one.
        """
        parts = text.strip().split(maxsplit=1)
        current = getattr(self.brain, kind, None)
        env_key = self._env_key_for(kind, self.brain.name)

        if len(parts) == 1 or not parts[1].strip():
            routing = ""
            router = getattr(self, "prompt_router", None)
            if kind == "model" and router is not None:
                automatic = router.enabled and self.brain.name not in router.manual
                routing = f"\nRouting: {'automatic' if automatic else 'manual'}."
                last = router.last.get(self.brain.name)
                if last:
                    routing += f"\nLast route: {last['status']} — {last['reason']}"
            if kind == "effort" and not getattr(self.brain, "supports_effort", False):
                self.telegram.send(
                    chat_id, f"{self.brain.name} has no reasoning-effort setting."
                )
                return
            other = ""
            if getattr(self.brain, "supports_effort", False):
                other_kind = "effort" if kind == "model" else "model"
                other = (f"\n{other_kind.capitalize()}: "
                         f"{getattr(self.brain, other_kind, None) or 'default'}")
            self.telegram.send(
                chat_id,
                f"{kind.capitalize()} [{self.brain.name}]: {current or 'default'}{other}\n"
                f"Change it with /{kind} <value>, or pick below.{routing}"
                + (f"\n{self.brain.model_help}"
                   if kind == "model" and getattr(self.brain, "model_help", None) else ""),
            )
            self._start_switcher(chat_id, kind)
            return
        if kind == "effort" and not getattr(self.brain, "supports_effort", False):
            self.telegram.send(
                chat_id, f"{self.brain.name} has no reasoning-effort setting."
            )
            return

        value = parts[1].strip()
        router = getattr(self, "prompt_router", None)
        if kind == "model" and value == "auto" and router is not None:
            if not router.model or not router.choices(self.brain.name):
                self.telegram.send(chat_id, "Configure a local classifier and qualified model profiles first.")
                return
            router.enabled = True
            router.manual.discard(self.brain.name)
            self.telegram.send(chat_id, f"Automatic model selection enabled for {self.brain.name}.")
            return
        if self._turn_is_active():
            # The active turn holds the brain lock for its whole duration. Waiting
            # for it here would stall this main loop, and /stop with it.
            self.telegram.send(
                chat_id,
                f"⏳ A turn is active. /stop it (or wait) before changing the {kind}.",
            )
            return
        async with self._brain_lock:
            setter = self.brain.set_model if kind == "model" else self.brain.set_effort
            try:
                error = await setter(value)
            except Exception as exc:  # noqa: BLE001 - keep the brain alive
                log.exception("Could not change %s to %r", kind, value)
                error = str(exc)
        if error:
            self.telegram.send(chat_id, f"⚠️ {error}")
            return

        if kind == "model" and router is not None:
            router.manual.add(self.brain.name)

        applied = getattr(self.brain, kind, None) or "default"
        self._remember_engine_setting(kind, self.brain.name, applied)
        persisted = True
        try:
            set_env_value(
                BASE_DIR / ".env",
                env_key,
                "" if applied == "default" else str(applied),
            )
        except OSError as exc:
            persisted = False
            log.warning("%s changed but .env persistence failed: %s", kind, exc)

        self._status_cache = self._basic_status()
        if hasattr(self, "_status_by_brain"):
            self._status_by_brain[self.brain.name] = dict(self._status_cache)
        self._write_console_status()
        asyncio.create_task(self._refresh_status(self.brain, force=True))

        note = "" if persisted else "\n(Could not write .env — this lasts until restart.)"
        self.telegram.send(
            chat_id,
            f"✅ {kind.capitalize()} [{self.brain.name}] → {applied}. "
            f"Takes effect on your next message.{note}",
        )

    def _start_switcher(self, chat_id: int, kind: str) -> None:
        """Offer the available models/efforts as Telegram buttons (in the background,
        so waiting for a tap never blocks the main loop or /stop)."""
        if not hasattr(getattr(self, "gate", None), "choose"):
            return
        previous = self._switcher_task
        if previous is not None and not previous.done():
            previous.cancel()
        self._switcher_task = asyncio.create_task(self._run_switcher(chat_id, kind))
        self._switcher_task.add_done_callback(self._log_switcher_error)

    @staticmethod
    def _log_switcher_error(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            log.warning("Model switcher failed: %s", task.exception())

    async def _run_switcher(self, chat_id: int, kind: str) -> None:
        brain = self.brain
        getter = getattr(brain, "model_options" if kind == "model" else "effort_options", None)
        try:
            options = list(await asyncio.wait_for(getter(), 8)) if getter else []
        except Exception as exc:  # noqa: BLE001 - the typed command still works
            log.info("Could not list %s options for %s: %s", kind, brain.name, exc)
            options = []
        current = getattr(brain, kind, None) or "default"
        if not options:
            return
        # Telegram prompts hold few buttons: keep the current value visible and
        # leave the rest to the "type another answer" button.
        options.sort(key=lambda item: item[0] != current)
        entries = [
            (value, ("● current" + (f" — {note}" if note else "")) if value == current else note)
            for value, note in options[:7]
        ]
        other_kind = "effort" if kind == "model" else "model"
        switch_label = None
        if getattr(brain, "supports_effort", False):
            switch_label = f"⚙ Change {other_kind}…"
            entries.append((switch_label, f"now {getattr(brain, other_kind, None) or 'default'}"))
        choice = await self.gate.choose(
            f"Switch {kind} for {brain.name} (now {current}):", entries
        )
        if not choice:
            return
        if choice == switch_label:
            await self._run_switcher(chat_id, other_kind)
            return
        if choice == current:
            self.telegram.send(chat_id, f"Already using {current}.")
            return
        await self._handle_engine_setting(chat_id, f"/{kind} {choice}", kind=kind)

    @staticmethod
    def _env_key_for(kind: str, brain_name: str) -> str:
        prefix = {"codex": "OVERLORD_CODEX_", "free": "OVERLORD_FREE_"}.get(brain_name, "OVERLORD_")
        return f"{prefix}{'MODEL' if kind == 'model' else 'EFFORT'}"

    @staticmethod
    def _remember_engine_setting(kind: str, brain_name: str, value: str) -> None:
        """Mirror the change into this process's config so a brain rebuilt by
        /brain (or an inactive brain's /status row) reflects it too."""
        global MODEL, EFFORT, CODEX_MODEL, CODEX_EFFORT
        stored = "" if value == "default" else value
        key = Bridge._env_key_for(kind, brain_name)
        os.environ[key] = stored
        if brain_name == "free":
            return  # the environment variable above is the only state it keeps
        if brain_name == "codex":
            if kind == "model":
                CODEX_MODEL = stored
            else:
                CODEX_EFFORT = stored
        else:
            if kind == "model":
                MODEL = stored or "opus"
            else:
                EFFORT = stored

    async def _handle_brain(self, chat_id: int, text: str) -> None:
        parts = text.strip().lower().split(maxsplit=1)
        if len(parts) == 1:
            self.telegram.send(
                chat_id,
                f"Active brain: {self.brain.name}\n"
                f"Switch with {' or '.join('/brain ' + n for n in VALID_BRAINS)}.",
            )
            return

        target = parts[1].strip()
        if target not in VALID_BRAINS:
            self.telegram.send(
                chat_id,
                f"Unknown brain: {target}\nChoose: {', '.join(VALID_BRAINS)}",
            )
            return
        if target == self.brain.name:
            self.telegram.send(chat_id, f"Already using {target}.")
            return

        if self._turn_is_active():
            # See _handle_engine_setting: waiting on the turn's lock would block /stop.
            self.telegram.send(
                chat_id, "⏳ A turn is active. /stop it (or wait) before switching brains."
            )
            return

        resumed = session_file_for(target).exists()
        try:
            candidate = build_brain(self.gate, target)
        except Exception as exc:  # noqa: BLE001 - keep the current brain alive
            log.exception("Could not build brain %s", target)
            self.telegram.send(
                chat_id,
                f"⚠️ Could not switch to {target}; still using {self.brain.name}: {exc}",
            )
            return
        async with self._brain_lock:
            try:
                await candidate.connect()
            except Exception as exc:  # noqa: BLE001 - keep the current brain alive
                log.exception("Could not switch brain to %s", target)
                try:
                    await candidate.disconnect()
                except Exception:  # noqa: BLE001 - failed candidate cleanup only
                    pass
                self.telegram.send(
                    chat_id,
                    f"⚠️ Could not switch to {target}; still using "
                    f"{self.brain.name}: {exc}",
                )
                return

            previous = self.brain
            self.brain = candidate
            self.brain_name = target
            if hasattr(self, "_status_by_brain"):
                self._status_cache = self._basic_status()
                self._status_by_brain[target] = dict(self._status_cache)
                self._write_console_status()
            self.tray.set_brain(target)
            self._pending_handoff = self._conversation_history.handoff_for(target)
            os.environ["OVERLORD_BRAIN"] = target
            persisted = True
            try:
                set_env_value(BASE_DIR / ".env", "OVERLORD_BRAIN", target)
            except OSError as exc:
                persisted = False
                log.warning("Brain switched but .env persistence failed: %s", exc)
            try:
                await previous.disconnect()
            except Exception as exc:  # noqa: BLE001 - new brain is already healthy
                log.warning("Previous brain disconnect after switch failed: %s", exc)

        resume_text = "resumed its saved session" if resumed else "started a new session"
        handoff_text = (
            f" {self._pending_handoff.entry_count} recent messages will be handed "
            "over with your next request."
            if self._pending_handoff is not None
            else " It is already caught up."
        )
        persistence_text = "" if persisted else " (restart selection was not saved)"
        self.telegram.send(
            chat_id,
            f"🔄 Switched to {target} — {resume_text}.{handoff_text}"
            f"{persistence_text}",
        )
        asyncio.create_task(self._refresh_status(self.brain))
        log.info("Runtime brain switch complete: %s -> %s", previous.name, target)

    def _record_turn_tokens(
        self, chat_id: int, prompt: str, *, outcome: str = "ok"
    ) -> None:
        """Book the just-finished turn and, optionally, report it inline.

        Runs outside the brain lock and never raises: a bad counter must not
        turn a delivered answer into an error message. A turn that reports no
        usage at all — Claude's shared-job path hands the turn to the terminal
        process, which does its own accounting — is silently skipped rather
        than booked as a zero.

        *outcome* is the bridge's own view ("stopped" when it interrupted the
        turn itself); anything else defers to what the engine reported, so a
        usage-cap failure is booked and labelled rather than lost.
        """
        try:
            usage = normalize_usage(
                getattr(self.brain, "last_turn_usage", None),
                brain=self.brain.name,
                model=getattr(self.brain, "model", None) or "default",
                cost_usd=getattr(self.brain, "last_turn_cost_usd", None),
                prompt=prompt,
                outcome=(
                    outcome
                    if outcome != "ok"
                    else getattr(self.brain, "last_turn_outcome", "ok")
                ),
            )
            if usage is None:
                return
            ledger = getattr(self, "tokens", None)
            if ledger is None:
                return
            ledger.record(usage)
            if TOKEN_FOOTER and self.brain.name != "free":
                self.telegram.send(chat_id, format_footer(usage, ledger.totals))
        except Exception as exc:  # noqa: BLE001 - accounting is never load-bearing
            log.warning("Could not record token usage for this turn: %s", exc)

    async def _route_prompt(self, chat_id: int, text: str) -> None:
        """Select within the active provider before sending the user turn once."""
        router = getattr(self, "prompt_router", None)
        if router is None or not router.enabled or self.brain.name in router.manual:
            return
        try:
            if self.brain.name == "claude":
                from modules import shared_job
                if await asyncio.to_thread(shared_job.live_job, self.brain.session_file) is not None:
                    router.last[self.brain.name] = {"status": "fallback",
                        "reason": "Shared terminal owns model selection"}
                    return
            catalog = getattr(self.brain, "routing_model_ids", None)
            model_ids = await catalog() if callable(catalog) else None
            selection = await router.select(
                self.brain.name, text, self._conversation_history.routing_context(),
                model_ids=model_ids,
            )
            if selection and selection["model"] != getattr(self.brain, "model", None):
                error = await self.brain.set_model(selection["model"])
                if error:
                    router.last[self.brain.name] = {"status": "fallback",
                        "reason": "Native model change refused"}
                else:
                    self.telegram.send(chat_id,
                        f"Model: {selection['model']} — {selection['reason']}")
        except asyncio.CancelledError:
            raise
        except Exception:
            router.last[self.brain.name] = {"status": "fallback",
                "reason": "Native model selection unavailable"}

    async def _handle_turn(self, chat_id: int, text: str) -> None:
        log.info("Dispatching turn: %s", text)
        chunks: list[str] = []
        outcome = "ok"
        history_recorded = False
        self.telegram.begin_typing(chat_id)
        try:
            async with self._brain_lock:
                await self._route_prompt(chat_id, text)
                query_text = (
                    add_handoff_to_turn(self._pending_handoff, text)
                    if self._pending_handoff is not None
                    else text
                )
                memory = getattr(self, "shared_memory", None)
                if memory is not None and self.brain.name != "free":
                    query_text = (memory.turn_context(native=self.brain.name != "free")
                                  + "\n\nCurrent conversation and owner request:\n" + query_text)
                query = (self.brain.query(query_text, project_work=self.free_work, chat_id=chat_id,
                                          shared_memory=memory)
                         if self.brain.name == "free" else self.brain.query(query_text))
                async for chunk in query:
                    if chunk and chunk.strip():
                        chunks.append(chunk.strip())
                if chunks:
                    self.telegram.send(chat_id, "\n\n".join(chunks))
                self._conversation_history.append_exchange(text, "\n\n".join(chunks))
                self._conversation_history.mark_seen(self.brain.name)
                self._pending_handoff = None
                history_recorded = True
        except asyncio.CancelledError:
            log.info("Active turn cancelled")
            # /stop and /steer land here. The turn still spent tokens, so mark
            # it and let the finally below book what the engine had reported.
            outcome = "stopped"
            raise
        except Exception as exc:  # noqa: BLE001 - report any turn failure to phone
            log.exception("Turn failed")
            outcome = "error"
            self.telegram.send(chat_id, f"⚠️ Error: {exc}")
        finally:
            if not history_recorded and outcome != "ok":
                if chunks:
                    self.telegram.send(chat_id, "\n\n".join(chunks))
                self._conversation_history.append_exchange(
                    text, "\n\n".join(chunks) +
                    f"\n[Turn {outcome}; effects may have occurred. "
                    "Reconcile before continuing; do not replay automatically.]",
                )
            # In the finally so every ending is accounted for: a clean answer,
            # a failure, a usage cap, and an interruption alike.
            self._record_turn_tokens(chat_id, text, outcome=outcome)
            self.telegram.end_typing(chat_id)

        if outcome == "ok" and getattr(self.brain, "last_turn_outcome", "ok") == "ok":
            try:
                await self._manage_context(chat_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Context management unavailable: %s", exc)


async def _run_bridge() -> None:
    startup_state.report("Initializing")
    bridge = Bridge()
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, bridge.request_shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda *_: bridge.request_shutdown())
    try:
        await bridge.run()
    finally:
        bridge.telegram.stop()


def main() -> None:
    singleton = SingleInstance()
    try:
        singleton.acquire()
    except AlreadyRunningError:
        startup_state.failed("Already running", "Overlord is already running on this machine.")
        log.error(
            "Overlord is already running on this machine. Use the notification-"
            "area icon to stop it before starting another instance."
        )
        return
    try:
        asyncio.run(_run_bridge())
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down Overlord bridge")
    except Exception as exc:
        startup_state.failed("Crashed", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        singleton.release()


if __name__ == "__main__":
    main()
