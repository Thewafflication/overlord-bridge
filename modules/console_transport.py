"""Local conversation and interaction controls, optionally mirrored to Telegram."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path


class ConsoleTransport:
    def __init__(self, path: Path, inbound, owner: int, on_send,
                 on_permission_response, on_choice_response, backend=None):
        self.path, self.inbound, self.owner = path, inbound, owner
        self.on_send = on_send
        self.on_permission_response = on_permission_response
        self.on_choice_response = on_choice_response
        self.backend = backend
        self.requests = {}
        self.typing = False
        self._lock = threading.RLock()
        self._publish()

    def _publish(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({"requests": self.requests, "typing": self.typing,
                                            "telegram_enabled": self.backend is not None}), encoding='utf-8')
            temporary.replace(self.path)

    def start(self):
        if self.backend:
            self.backend.start()

    def wait_ready(self, timeout=30):
        return self.backend.wait_ready(timeout) if self.backend else True

    def disable_backend(self):
        if self.backend:
            self.backend.stop()
        self.backend = None
        self._publish()

    def stop(self):
        if self.backend:
            self.backend.stop()
        self.requests.clear()
        self.typing = False
        self._publish()

    def send(self, chat_id, text, *, mirror=True):
        if self.backend:
            self.backend.send(chat_id, text, mirror=mirror)
        elif mirror and text:
            self.on_send(chat_id, text)

    send_response = send

    def begin_typing(self, chat_id):
        self.typing = True
        self._publish()
        if self.backend:
            self.backend.begin_typing(chat_id)

    def end_typing(self, chat_id):
        self.typing = False
        self._publish()
        if self.backend:
            self.backend.end_typing(chat_id)

    def _add(self, request_id, kind, prompt, options):
        self.requests[request_id] = {"kind": kind, "prompt": prompt, "options": options,
                                     "expires": time.time() + (600 if kind == "command" else 86400)}
        self._publish()

    def ask_permission(self, chat_id, prompt_text, request_id):
        self._add(request_id, 'permission', prompt_text,
                  [('Allow once', 'allow'), ('Deny', 'deny'), ('Exact action for session', 'session')])
        if self.backend:
            self.backend.ask_permission(chat_id, prompt_text, request_id)

    def cancel_permission(self, chat_id, request_id):
        self.requests.pop(request_id, None)
        self._publish()
        if self.backend:
            self.backend.cancel_permission(chat_id, request_id)

    def ask_choice(self, chat_id, prompt_text, request_id, options):
        self._add(request_id, 'choice', prompt_text, [(label + (f' — {note}' if note else ''), label)
                                                    for label, note in options])
        if self.backend:
            self.backend.ask_choice(chat_id, prompt_text, request_id, options)

    def cancel_choice(self, chat_id, request_id):
        self.requests.pop(request_id, None)
        self._publish()
        if self.backend:
            self.backend.cancel_choice(chat_id, request_id)

    def send_command_options(self, chat_id, title, options):
        self.clear_command_options()
        self._add(uuid.uuid4().hex, 'command', title, options)
        if self.backend:
            self.backend.send_command_options(chat_id, title, options)

    def clear_command_options(self):
        self.requests = {key: value for key, value in self.requests.items() if value['kind'] != 'command'}
        self._publish()
        if self.backend:
            self.backend.clear_command_options()

    def respond(self, request_id, answer):
        request = self.requests.get(request_id)
        if not request or time.time() > request['expires'] or not isinstance(answer, str):
            return False
        values = [value for _, value in request['options']]
        if request['kind'] != 'choice' and answer not in values:
            return False
        self.requests.pop(request_id, None)
        self._publish()
        if request['kind'] == 'permission':
            self.on_permission_response(request_id, answer)
        elif request['kind'] == 'choice':
            self.on_choice_response(request_id, answer)
        else:
            if self.backend:
                self.backend.clear_command_options()
            self.inbound.put((self.owner, answer))
        return True
