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
  * **Permission prompts** -- ``ask_permission`` sends an Allow/Deny inline
    keyboard; taps are routed back through ``on_permission_response``.
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
from telegram.error import Conflict, NetworkError, RetryAfter, TelegramError
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


class TelegramHandler(threading.Thread):
    """Runs Telegram long-polling in a dedicated thread/event loop."""

    def __init__(
        self,
        token: str,
        inbound_queue: "Queue[tuple[int, str]]",
        owner_chat_id: int,
        on_permission_response: Optional[Callable[[str, bool], None]] = None,
    ) -> None:
        super().__init__(daemon=True, name="telegram-handler")
        self.token = token
        self.inbound_queue = inbound_queue
        self.owner_chat_id = int(owner_chat_id)
        self.on_permission_response = on_permission_response

        self.application = Application.builder().token(token).build()
        # Reuse the application's initialized bot and HTTP connection pool for
        # polling, replies, typing indicators, and permission prompts.
        self.bot = self.application.bot
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._typing_tasks: dict[int, asyncio.Task] = {}

        self.application.add_handler(
            CommandHandler(
                ("new", "help", "status", "stop", "steer", "brain"),
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
        if command not in {
            "/new",
            "/help",
            "/status",
            "/stop",
            "/steer",
            "/brain",
        }:
            return
        normalized = command
        if command in {"/brain", "/steer"} and len(parts) > 1:
            normalized += " " + parts[1].strip()
        self.inbound_queue.put((chat_id, normalized))
        log.info("Owner requested %s", normalized)

    async def _handle_callback(self, update: Update, context: CallbackContext) -> None:
        """Handle Allow/Deny taps from a permission prompt."""
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        chat_id = query.message.chat_id if query.message else None
        if chat_id != self.owner_chat_id:
            return
        # callback_data format: "perm:<request_id>:<allow|deny>"
        try:
            _, request_id, decision = (query.data or "").split(":", 2)
        except ValueError:
            return
        allow = decision == "allow"
        try:
            original = query.message.text if query.message else ""
            verdict = "✅ Allowed" if allow else "⛔ Denied"
            await query.edit_message_text(f"{original}\n\n{verdict}")
        except Exception as exc:  # editing is best-effort
            log.debug("Could not edit permission message: %s", exc)
        if self.on_permission_response is not None:
            self.on_permission_response(request_id, allow)

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
        """Send an Allow/Deny prompt; the answer arrives via on_permission_response."""
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._ask_permission(chat_id, prompt_text, request_id), self.loop
        )

    async def _ask_permission(
        self, chat_id: int, prompt_text: str, request_id: str
    ) -> None:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Allow", callback_data=f"perm:{request_id}:allow"
                    ),
                    InlineKeyboardButton(
                        "⛔ Deny", callback_data=f"perm:{request_id}:deny"
                    ),
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
            self.on_permission_response(request_id, False)

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
