"""Telegram I/O for the Overlord bridge.

Reference shape borrowed from an earlier assistant of Ben's: a
``threading.Thread`` that runs python-telegram-bot's async polling in its own
event loop, feeds inbound messages onto a queue, and exposes a thread-safe
``send`` for replies.

Improvements over the original:
  * **Owner gating** -- only the configured OWNER_CHAT_ID is ever serviced;
    every other update is dropped. The Overlord can touch the filesystem, so
    this is non-negotiable.
  * **Graceful shutdown** via ``stop()`` so the systemd service stops cleanly.
  * **4096-char chunking** so long Overlord replies don't get rejected by the
    Telegram API.
  * **Permission prompts** -- ``ask_permission`` sends Allow once, Deny, and
    exact-action session grant buttons; taps route through
    ``on_permission_response``.
  * No Joshua-specific dependencies (uses stdlib ``logging``).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from queue import Queue
from typing import Awaitable, Callable, Iterator, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest, Conflict, NetworkError, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

log = logging.getLogger("overlord.telegram")

# Telegram hard limit on a single text message.
MAX_MESSAGE_LEN = 4096
COMMANDS = (
    "new", "help", "status", "stop", "steer", "brain", "tokens", "quote",
    "model", "effort", "questions", "reply", "cancelquestion", "permissions",
    "context", "compact", "work",
)


class TelegramHandler(threading.Thread):
    """Runs Telegram long-polling in a dedicated thread/event loop."""

    def __init__(
        self,
        token: str,
        inbound_queue: "Queue[tuple[int, str]]",
        owner_chat_id: int,
        on_permission_response: Optional[Callable[[str, str], None]] = None,
        on_choice_response: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        super().__init__(daemon=True, name="telegram-handler")
        self.token = token
        self.inbound_queue = inbound_queue
        self.owner_chat_id = int(owner_chat_id)
        self.on_permission_response = on_permission_response
        self.on_choice_response = on_choice_response

        self.application = Application.builder().token(token).build()
        # Reuse the application's initialized bot and HTTP connection pool for
        # polling, replies, typing indicators, and permission prompts.
        self.bot = self.application.bot
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._typing_tasks: dict[int, asyncio.Task] = {}
        self._choice_for_chat: dict[int, str] = {}
        self._choice_options: dict[str, list[str]] = {}
        self._choice_typing: set[str] = set()
        self._choice_messages: dict[str, int] = {}
        self._choice_prompts: dict[str, str] = {}
        self._permission_live: dict[str, int] = {}

        self.application.add_handler(
            CommandHandler(
                COMMANDS,
                self._handle_command,
            )
        )
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))

    # ------------------------------------------------------------------ inbound
    async def _handle_message(self, update: Update, context: CallbackContext) -> None:
        if update.message is None:
            return
        chat_id = update.message.chat_id
        text = update.message.text or ""
        if chat_id != self.owner_chat_id:
            log.warning("Dropping message from unauthorized chat_id=%s", chat_id)
            return
        self._ensure_choice_state()
        request_id = self._choice_for_chat.get(chat_id)
        reply_to = getattr(update.message, "reply_to_message", None)
        linked_reply = (
            reply_to is not None
            and getattr(reply_to, "message_id", None)
            == self._choice_messages.get(request_id)
        )
        if request_id and (request_id in self._choice_typing or linked_reply):
            if not text.strip():
                return
            self._answer_choice(chat_id, request_id, text)
            log.info("Owner supplied a typed choice response")
            return
        self.inbound_queue.put((chat_id, text))
        log.info("Message from owner: %s", text)

    async def _handle_command(self, update: Update, context: CallbackContext) -> None:
        """Normalize owner-only Telegram commands for the bridge main loop."""
        if update.message is None:
            return
        chat_id = update.message.chat_id
        if chat_id != self.owner_chat_id:
            log.warning("Dropping command from unauthorized chat_id=%s", chat_id)
            return
        parts = (update.message.text or "").strip().split(maxsplit=1)
        command = parts[0].split("@", 1)[0].lower() if parts else ""
        if command.lstrip("/") not in COMMANDS:
            return
        if command in {"/questions", "/reply", "/cancelquestion"}:
            await self._handle_question_command(chat_id, command, parts[1:])
            return
        normalized = command
        if command not in {"/new", "/help", "/stop"} and len(parts) > 1:
            normalized += " " + parts[1].strip()
        self.inbound_queue.put((chat_id, normalized))
        log.info("Owner requested %s", normalized)

    def _ensure_choice_state(self) -> None:
        """Initialize optional state for handlers restored or built in tests."""
        for name, factory in (
            ("_choice_typing", set), ("_choice_messages", dict),
            ("_choice_prompts", dict),
        ):
            if not hasattr(self, name):
                setattr(self, name, factory())

    def _answer_choice(self, chat_id: int, request_id: str, answer: str) -> bool:
        if self._choice_for_chat.get(chat_id) != request_id:
            return False
        self._cancel_choice(chat_id, request_id)
        if self.on_choice_response is not None:
            self.on_choice_response(request_id, answer)
        return True

    async def _handle_question_command(
        self, chat_id: int, command: str, arguments: list[str]
    ) -> None:
        self._ensure_choice_state()
        current = self._choice_for_chat.get(chat_id)
        if command == "/questions":
            text = (
                f"Pending question: {current}\n"
                f"{self._choice_prompts.get(current, '')}\n\n"
                f"/reply {current} <answer>\n/cancelquestion {current}"
                if current else "No question is pending."
            )
            await self._send(chat_id, text)
            return
        fields = arguments[0].split(maxsplit=1) if arguments else []
        if not fields or fields[0] != current:
            await self._send(
                chat_id, "Question ID is missing or expired. Use /questions."
            )
            return
        if command == "/reply" and (len(fields) < 2 or not fields[1].strip()):
            await self._send(chat_id, f"Usage: /reply {current} <answer>")
            return
        answer = fields[1].strip() if command == "/reply" else ""
        self._answer_choice(chat_id, current, answer)
        await self._send(
            chat_id, "Answer submitted." if answer else "Question cancelled."
        )

    async def _handle_callback(self, update: Update, context: CallbackContext) -> None:
        """Handle permission and model-question inline keyboards."""
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        chat_id = query.message.chat_id if query.message else None
        if chat_id != self.owner_chat_id:
            return
        # callback_data: "perm:<id>:<decision>" or "choice:<id>:<index|other>".
        try:
            kind, request_id, decision = (query.data or "").split(":", 2)
        except ValueError:
            return
        if kind == "choice":
            await self._handle_choice_callback(query, chat_id, request_id, decision)
            return
        if kind != "perm":
            return
        live = getattr(self, "_permission_live", {})
        if live.get(request_id) != chat_id:
            return
        verdicts = {
            "allow": "✅ Allowed once",
            "deny": "⛔ Denied",
            "session": "✅ Allowed this exact action for the current session",
        }
        verdict = verdicts.get(decision)
        if verdict is None:
            return
        live.pop(request_id, None)
        if self.on_permission_response is not None:
            self.on_permission_response(request_id, decision)
        try:
            original = query.message.text if query.message else ""
            await query.edit_message_text(f"{original}\n\n{verdict}")
        except Exception as exc:  # editing is best-effort
            log.debug("Could not edit permission message: %s", exc)

    async def _handle_choice_callback(
        self, query, chat_id: int, request_id: str, decision: str
    ) -> None:
        options = self._choice_options.get(request_id)
        if options is None or self._choice_for_chat.get(chat_id) != request_id:
            return
        original = query.message.text if query.message else ""
        if decision == "other":
            self._ensure_choice_state()
            self._choice_typing.add(request_id)
            try:
                await query.edit_message_text(
                    f"{original}\n\n✍️ Reply with your own answer."
                )
            except Exception as exc:
                log.debug("Could not edit choice message: %s", exc)
            return
        try:
            index = int(decision)
            if index < 0:
                return
            answer = options[index]
        except (ValueError, IndexError):
            return
        self._answer_choice(chat_id, request_id, answer)
        try:
            await query.edit_message_text(f"{original}\n\n✅ Selected: {answer}")
        except Exception as exc:
            log.debug("Could not edit choice message: %s", exc)

    # ------------------------------------------------------------------ outbound
    def send(self, chat_id: int, text: str) -> None:
        """Thread-safe: queue a (chunked) reply onto the polling loop."""
        if not text or self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._send(chat_id, text), self.loop)

    # Joshua-compatible alias.
    send_response = send

    async def _send(self, chat_id: int, text: str) -> None:
        for chunk in _chunks(text):
            await self._telegram_call(
                "send_message",
                lambda chunk=chunk: self.bot.send_message(
                    chat_id=chat_id, text=chunk
                ),
            )

    async def _telegram_call(
        self,
        label: str,
        operation: Callable[[], Awaitable[object]],
        attempts: int = 4,
        quiet: bool = False,
    ) -> bool:
        """Retry transient Telegram failures instead of silently losing output."""
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                await operation()
                return True
            except RetryAfter as exc:
                last_error = exc
                retry_after = exc.retry_after
                delay = (
                    retry_after.total_seconds()
                    if hasattr(retry_after, "total_seconds")
                    else float(retry_after)
                )
            except BadRequest as exc:
                # A NetworkError subclass, but the API understood and refused the
                # request (chat not found, message too long); retrying cannot help.
                log.error("%s rejected by Telegram: %s", label, exc)
                return False
            except NetworkError as exc:
                last_error = exc
                delay = min(0.5 * (2 ** (attempt - 1)), 4.0)
            except TelegramError as exc:
                log.error("%s failed permanently: %s", label, exc)
                return False
            except Exception as exc:  # noqa: BLE001 - keep I/O thread alive
                log.error("%s failed: %s", label, exc)
                return False

            if attempt == attempts:
                if not quiet:
                    log.error(
                        "%s failed after %s attempts: %s",
                        label,
                        attempts,
                        last_error,
                    )
                return False
            if not quiet:
                log.warning(
                    "%s transient failure; retrying in %.1fs (%s/%s)",
                    label,
                    delay,
                    attempt,
                    attempts,
                )
            await asyncio.sleep(delay)
        return False

    def begin_typing(self, chat_id: int) -> None:
        """Show Telegram's typing indicator until :meth:`end_typing`."""
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(self._begin_typing(chat_id), self.loop)

    async def _begin_typing(self, chat_id: int) -> None:
        old = self._typing_tasks.pop(chat_id, None)
        if old is not None:
            old.cancel()
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    async def _typing_loop(self, chat_id: int) -> None:
        try:
            while True:
                await self._telegram_call(
                    "typing indicator",
                    lambda: self.bot.send_chat_action(
                        chat_id=chat_id, action=ChatAction.TYPING
                    ),
                    attempts=1,
                    quiet=True,
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            return

    def end_typing(self, chat_id: int) -> None:
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(self._end_typing(chat_id), self.loop)

    async def _end_typing(self, chat_id: int) -> None:
        task = self._typing_tasks.pop(chat_id, None)
        if task is not None:
            task.cancel()

    def ask_permission(self, chat_id: int, prompt_text: str, request_id: str) -> None:
        """Send a three-choice permission prompt."""
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._ask_permission(chat_id, prompt_text, request_id), self.loop
        )

    async def _ask_permission(
        self, chat_id: int, prompt_text: str, request_id: str
    ) -> None:
        if not hasattr(self, "_permission_live"):
            self._permission_live = {}
        self._permission_live[request_id] = chat_id
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Allow once", callback_data=f"perm:{request_id}:allow"
                    ),
                    InlineKeyboardButton(
                        "⛔ Deny", callback_data=f"perm:{request_id}:deny"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "✅ This exact action (session)",
                        callback_data=f"perm:{request_id}:session",
                    )
                ]
            ]
        )
        delivered = await self._telegram_call(
            "ask_permission",
            lambda: self.bot.send_message(
                chat_id=chat_id,
                text=prompt_text[:MAX_MESSAGE_LEN],
                reply_markup=keyboard,
            ),
        )
        if not delivered and self.on_permission_response is not None:
            # Do not leave the brain blocked until the full permission timeout
            # when the owner never had a prompt they could approve.
            self.on_permission_response(request_id, "deny")
            self._permission_live.pop(request_id, None)

    def cancel_permission(self, chat_id: int, request_id: str) -> None:
        """Invalidate buttons belonging to a completed or cancelled request."""
        if self.loop is not None:
            self.loop.call_soon_threadsafe(
                self._cancel_permission, chat_id, request_id
            )

    def _cancel_permission(self, chat_id: int, request_id: str) -> None:
        live = getattr(self, "_permission_live", {})
        if live.get(request_id) == chat_id:
            live.pop(request_id, None)

    def ask_choice(
        self,
        chat_id: int,
        prompt_text: str,
        request_id: str,
        options: list[tuple[str, str]],
    ) -> None:
        """Send model-authored choices; a tap or typed reply resolves them."""
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._ask_choice(chat_id, prompt_text, request_id, options), self.loop
        )

    async def _ask_choice(
        self,
        chat_id: int,
        prompt_text: str,
        request_id: str,
        options: list[tuple[str, str]],
    ) -> None:
        labels = [label for label, _description in options]
        self._ensure_choice_state()
        previous = self._choice_for_chat.get(chat_id)
        if previous and previous != request_id:
            self._answer_choice(chat_id, previous, "")
        self._choice_for_chat[chat_id] = request_id
        self._choice_options[request_id] = labels
        self._choice_prompts[request_id] = prompt_text[:2000]
        rows = [
            [
                InlineKeyboardButton(
                    label[:64], callback_data=f"choice:{request_id}:{index}"
                )
            ]
            for index, label in enumerate(labels)
        ]
        rows.append(
            [
                InlineKeyboardButton(
                    "✍️ Type another answer",
                    callback_data=f"choice:{request_id}:other",
                )
            ]
        )
        details = "\n".join(
            f"• {label}: {description}"
            for label, description in options
            if description
        )
        text = prompt_text
        if details:
            text += f"\n\n{details}"
        text += (
            "\n\nTap an option, select Type another answer, or reply directly "
            f"to this message.\nQuestion ID: {request_id}\n"
            f"/reply {request_id} <answer>"
        )

        async def send_prompt():
            message = await self.bot.send_message(
                chat_id=chat_id, text=text[:MAX_MESSAGE_LEN],
                reply_markup=InlineKeyboardMarkup(rows),
            )
            if self._choice_for_chat.get(chat_id) == request_id:
                message_id = getattr(message, "message_id", None)
                if message_id is not None:
                    self._choice_messages[request_id] = message_id
            return message

        delivered = await self._telegram_call(
            "ask_choice", send_prompt,
        )
        if not delivered:
            self._answer_choice(chat_id, request_id, "")

    def cancel_choice(self, chat_id: int, request_id: str) -> None:
        """Forget a timed-out/cancelled question without consuming later chat."""
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self._cancel_choice, chat_id, request_id)

    def _cancel_choice(self, chat_id: int, request_id: str) -> None:
        self._ensure_choice_state()
        if self._choice_for_chat.get(chat_id) == request_id:
            self._choice_for_chat.pop(chat_id, None)
        self._choice_options.pop(request_id, None)
        self._choice_typing.discard(request_id)
        self._choice_messages.pop(request_id, None)
        self._choice_prompts.pop(request_id, None)

    # ------------------------------------------------------------------ lifecycle
    async def _initialize_application(self) -> bool:
        initialized = await self._telegram_call(
            "Telegram initialization",
            self.application.initialize,
            attempts=6,
        )
        if not initialized:
            log.error("Telegram initialization did not recover; handler stopped")
            return False
        await self.application.start()
        await self.application.updater.start_polling(
            bootstrap_retries=5,
            error_callback=self._polling_error,
        )
        return True

    @staticmethod
    def _polling_error(error: TelegramError) -> None:
        """Keep expected polling failures useful without multi-page tracebacks."""
        if isinstance(error, Conflict):
            log.error(
                "Telegram polling conflict: another Overlord instance is using "
                "this bot token"
            )
        elif isinstance(error, NetworkError):
            log.warning("Telegram polling network error; retrying: %s", error)
        else:
            log.error("Telegram polling error: %s", error)

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        if not self.loop.run_until_complete(self._initialize_application()):
            return
        self._ready.set()
        log.info("Telegram polling started")
        self.loop.run_forever()

    def wait_ready(self, timeout: float = 30.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        """Stop polling and tear down the event loop cleanly."""
        if self.loop is None or not self.loop.is_running():
            return

        async def _shutdown() -> None:
            try:
                for task in self._typing_tasks.values():
                    task.cancel()
                self._typing_tasks.clear()
                if self.application.updater and self.application.updater.running:
                    await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            except Exception as exc:
                log.error("Error during Telegram shutdown: %s", exc)

        try:
            asyncio.run_coroutine_threadsafe(_shutdown(), self.loop).result(timeout=10)
        except Exception as exc:
            log.error("Shutdown future failed: %s", exc)
        self.loop.call_soon_threadsafe(self.loop.stop)


def _chunks(text: str) -> Iterator[str]:
    for i in range(0, len(text), MAX_MESSAGE_LEN):
        yield text[i : i + MAX_MESSAGE_LEN]
