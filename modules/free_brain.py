"""FreeBrain: plain chat over free-tier models, paced by their usage limits.

A text-only :class:`Brain`. It has no tools, reads no files and runs no commands,
so it needs no permission gate; it is for conversation, not for operating the
machine. Models come from two providers that publish free tiers:

  * ``nvidia``     NVIDIA NIM (the same key the NVIDIA workers use)
  * ``openrouter`` OpenRouter models whose ID ends in ``:free``. Opt-in, because
                   chat content is sent to third-party providers, and admitted
                   only while the live catalog prices them at zero.

Usage limits are enforced here, before a request is made, rather than discovered
through errors: a per-provider requests-per-minute window and an optional daily
cap (persisted, so a restart cannot reset them), plus a per-model cooldown taken
from ``Retry-After`` / rate-limit headers on a 429. A model that is cooling down
or out of budget is skipped in favour of the next configured one; when every
model is spent the owner is told when the first becomes available again.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from modules.brain import Brain
from modules.free_services import OPENROUTER_BASE, free_provider_policy, validate_free_model
from modules.workers import (
    DEFAULT_NVIDIA_API_BASE,
    _NVIDIA_MODEL_ALIASES,
    _NVIDIA_MODEL_PAYLOAD_OVERRIDES,
    _http_get_json,
)

log = logging.getLogger("overlord.free")

PROVIDERS = ("nvidia", "openrouter")
# "openrouter:free" means: discover the best zero-priced chat models from the live
# catalog (fixed IDs go stale quickly). OpenRouter leads, NVIDIA follows.
DEFAULT_MODELS = "openrouter:free,nvidia:gpt-oss,nvidia:mistral,nvidia:llama"
DISCOVER = "free"
DISCOVER_LIMIT = 3
# Used only when the catalog cannot be fetched at start-up.
FALLBACK_OPENROUTER = (
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
)
_NOT_CHAT = ("safety", "guard", "embed", "moderation", "rerank")
# Conservative published-tier defaults: OpenRouter's free tier is about 20/min
# and 50/day without credits; NIM is rate limited per minute only.
DEFAULT_LIMITS = {"nvidia": (20, 0), "openrouter": (15, 45)}
SYSTEM_PROMPT = (
    "You are the Overlord's chat assistant, reached through Telegram. You are a "
    "text-only model: you cannot run commands, read or edit files, browse, or "
    "dispatch workers. Answer directly and concisely; if a request needs those "
    "abilities, say so and suggest switching to the claude or codex brain."
)


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


def parse_models(raw: str) -> list[ModelSpec]:
    """``provider:model`` entries, comma separated. A bare name is a NIM alias or ID."""
    specs: list[ModelSpec] = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        provider, sep, model = item.partition(":")
        if not sep or provider.lower() not in PROVIDERS:
            provider, model = "nvidia", item
        provider = provider.lower()
        model = model.strip()
        if provider == "nvidia":
            model = _NVIDIA_MODEL_ALIASES.get(model.lower(), model)
        if not model:
            continue
        spec = ModelSpec(provider, model)
        if spec not in specs:
            specs.append(spec)
    return specs


def discover_free_models(catalog: Any, limit: int = DISCOVER_LIMIT) -> list[str]:
    """Best zero-priced OpenRouter chat models: largest context, one per vendor."""
    if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
        return []
    candidates = []
    for entry in catalog["data"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        model = entry["id"]
        if not model.endswith(":free") or any(word in model.lower() for word in _NOT_CHAT):
            continue
        try:
            validate_free_model(catalog, model, require_tools=False)
        except ValueError:
            continue
        context = entry.get("context_length")
        candidates.append((-(context if isinstance(context, int) else 0), model))
    chosen, vendors = [], set()
    for _, model in sorted(candidates):
        vendor = model.split("/", 1)[0]
        if vendor in vendors:
            continue
        vendors.add(vendor)
        chosen.append(model)
        if len(chosen) >= limit:
            break
    return chosen


def format_wait(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def _parse_duration(value: Any) -> float | None:
    """Seconds from ``30``, ``1.5``, ``45s``, ``2m``, ``1m30s`` or an HTTP date."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    total, number, seen = 0.0, "", False
    for ch in text:
        if ch.isdigit() or ch == ".":
            number += ch
        elif ch in "hms" and number:
            total += float(number) * {"h": 3600, "m": 60, "s": 1}[ch]
            number, seen = "", True
        else:
            seen = False
            break
    if seen and not number:
        return total
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(str(value))
        return max(0.0, when.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


class UsageLimiter:
    """Per-provider request pacing plus per-model cooldowns, persisted to disk."""

    def __init__(
        self,
        path: Path | None,
        limits: dict[str, tuple[int, int]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.limits = limits
        self.clock = clock
        self._recent: dict[str, list[float]] = {}
        self._daily: dict[str, dict[str, Any]] = {}
        self._cooldown: dict[str, float] = {}
        self._load()

    # -- queries -------------------------------------------------------------
    def _day(self, now: float) -> str:
        return datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%d")

    def _seconds_to_next_day(self, now: float) -> float:
        moment = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
        tomorrow = (moment + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return (tomorrow - moment).total_seconds()

    def _prune(self, provider: str, now: float) -> list[float]:
        recent = [t for t in self._recent.get(provider, []) if 0 <= now - t < 60]
        self._recent[provider] = recent
        return recent

    def daily_count(self, provider: str) -> int:
        entry = self._daily.get(provider)
        return int(entry["count"]) if entry and entry.get("day") == self._day(self.clock()) else 0

    def availability(self, spec: ModelSpec) -> tuple[float, str]:
        """(seconds until a request is allowed, why). 0 means go ahead."""
        now = self.clock()
        rpm, daily = self.limits.get(spec.provider, (0, 0))
        wait, reason = 0.0, ""
        for key, label in ((spec.provider, "provider cooling down"), (spec.key, "cooling down")):
            remaining = self._cooldown.get(key, 0.0) - now
            if remaining > wait:
                wait, reason = remaining, label
        if rpm > 0:
            recent = self._prune(spec.provider, now)
            if len(recent) >= rpm:
                needed = min(recent) + 60 - now
                if needed > wait:
                    wait, reason = needed, f"{rpm}/min limit"
        if daily > 0 and self.daily_count(spec.provider) >= daily:
            needed = self._seconds_to_next_day(now)
            if needed > wait:
                wait, reason = needed, f"{daily}/day cap"
        return max(0.0, wait), reason

    def snapshot(self, provider: str) -> dict[str, int]:
        rpm, daily = self.limits.get(provider, (0, 0))
        return {
            "minute_used": len(self._prune(provider, self.clock())), "minute_cap": rpm,
            "day_used": self.daily_count(provider), "day_cap": daily,
        }

    def cooling(self, spec: ModelSpec) -> float:
        now = self.clock()
        return max(self._cooldown.get(spec.key, 0.0), self._cooldown.get(spec.provider, 0.0)) - now

    # -- updates -------------------------------------------------------------
    def record(self, spec: ModelSpec) -> None:
        now = self.clock()
        self._prune(spec.provider, now).append(now)
        day = self._day(now)
        entry = self._daily.get(spec.provider)
        if not entry or entry.get("day") != day:
            entry = self._daily[spec.provider] = {"day": day, "count": 0}
        entry["count"] += 1
        self._save()

    def cool_down(self, key: str, seconds: float) -> None:
        self._cooldown[key] = max(self._cooldown.get(key, 0.0), self.clock() + max(1.0, seconds))
        self._save()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> None:
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        now = self.clock()
        for provider, stamps in (data.get("recent") or {}).items():
            if isinstance(stamps, list):
                self._recent[provider] = [
                    float(t) for t in stamps
                    if isinstance(t, (int, float)) and not isinstance(t, bool) and 0 <= now - t < 60
                ]
        for provider, entry in (data.get("daily") or {}).items():
            if (isinstance(entry, dict) and isinstance(entry.get("day"), str)
                    and type(entry.get("count")) is int and entry["count"] >= 0):
                self._daily[provider] = {"day": entry["day"], "count": entry["count"]}
        for key, until in (data.get("cooldown") or {}).items():
            if isinstance(until, (int, float)) and not isinstance(until, bool) and until > now:
                self._cooldown[key] = float(until)

    def _save(self) -> None:
        if self.path is None:
            return
        now = self.clock()
        payload = {
            "recent": {p: self._prune(p, now) for p in list(self._recent)},
            "daily": self._daily,
            "cooldown": {k: v for k, v in self._cooldown.items() if v > now},
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            log.debug("Could not persist free-model usage: %s", exc)


def _json_or_empty(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never forward the API key to a redirect target


def _post_sync(url: str, payload: dict[str, Any], api_key: str, timeout: float):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "Accept": "application/json", "Connection": "close"},
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, \
                _json_or_empty(response.read())
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
        return exc.code, headers, _json_or_empty(exc.read() or b"")


async def _post(url: str, payload: dict[str, Any], api_key: str, timeout: float):
    return await asyncio.to_thread(_post_sync, url, payload, api_key, timeout)


class FreeBrain(Brain):
    name = "free"
    supports_effort = False

    def __init__(
        self,
        *,
        session_file: Path,
        models: list[ModelSpec],
        keys: dict[str, str],
        limiter: UsageLimiter,
        model: str | None = None,
        bases: dict[str, str] | None = None,
        openrouter_enabled: bool = False,
        max_tokens: int = 2048,
        history_chars: int = 24_000,
        timeout: float = 90.0,
        max_wait: float = 8.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.session_file = session_file
        self.limiter = limiter
        self.keys = {k: (v or "").strip() for k, v in keys.items()}
        self.bases = {"nvidia": DEFAULT_NVIDIA_API_BASE, "openrouter": OPENROUTER_BASE, **(bases or {})}
        self.max_tokens = max(64, max_tokens)
        self.history_chars = max(2_000, history_chars)
        self.timeout = timeout
        self.max_wait = max_wait
        self._sleep = sleep
        self._admitted: dict[str, str | None] = {}  # openrouter model -> None ok | reason
        self.unavailable: list[str] = []
        self.models: list[ModelSpec] = []
        self._discover_at: int | None = None
        self._preferred = model
        for spec in models:
            if spec.provider == "openrouter" and spec.model == DISCOVER:
                if not self.keys.get("openrouter"):
                    self.unavailable.append("openrouter:free: no openrouter API key configured")
                elif not openrouter_enabled:
                    self.unavailable.append("openrouter:free: disabled (OVERLORD_FREE_OPENROUTER_ENABLED=0)")
                else:
                    self._discover_at = len(self.models)
                continue
            if not self.keys.get(spec.provider):
                self.unavailable.append(f"{spec.key}: no {spec.provider} API key configured")
            elif spec.provider == "openrouter" and not openrouter_enabled:
                self.unavailable.append(
                    f"{spec.key}: OpenRouter sends chat to third parties; set "
                    "OVERLORD_FREE_OPENROUTER_ENABLED=1 to allow it"
                )
            elif spec.provider == "openrouter" and not spec.model.endswith(":free"):
                self.unavailable.append(f"{spec.key}: OpenRouter models must end in :free")
            else:
                self.models.append(spec)
        chosen = self._resolve(model) if model else None
        default = chosen or (self.models[0] if self.models else None)
        self.model: str | None = default.key if default else None
        self.last_turn_usage: dict[str, Any] | None = None
        self.last_turn_cost_usd: float | None = None
        self.last_turn_outcome = "ok"
        self._history: list[dict[str, str]] = []

    # ------------------------------------------------------------ model choice
    def _resolve(self, value: str | None) -> ModelSpec | None:
        text = (value or "").strip()
        if not text or not self.models:
            return None
        if text.isdigit():
            index = int(text) - 1
            return self.models[index] if 0 <= index < len(self.models) else None
        lowered = text.lower()
        alias = _NVIDIA_MODEL_ALIASES.get(lowered, text).lower()
        for spec in self.models:
            if lowered in (spec.key.lower(), spec.model.lower()) or alias == spec.model.lower():
                return spec
        hits = [s for s in self.models if lowered in s.key.lower()]
        return hits[0] if len(hits) == 1 else None

    @property
    def model_help(self) -> str:
        """Numbered list of the models /model can switch between."""
        if not self.models:
            return "No free model is usable yet.\n" + "\n".join(self.unavailable)
        lines = [f"{n}. {s.key}{'  ← current' if s.key == self.model else ''}"
                 for n, s in enumerate(self.models, 1)]
        return "Available:\n" + "\n".join(lines)

    async def model_options(self) -> list[tuple[str, str]]:
        options = []
        for spec in self.models:
            wait, reason = self.limiter.availability(spec)
            options.append((spec.key, f"{reason}, back in {format_wait(wait)}" if wait > 0 else "ready"))
        return options

    async def set_model(self, model: str) -> str | None:
        spec = self._resolve(model)
        if spec is None:
            return f"Unknown free model {model!r}. {self.model_help}"
        self.model = spec.key
        return None

    def _order(self) -> list[ModelSpec]:
        chosen = self._resolve(self.model)
        rest = [s for s in self.models if s != chosen]
        return ([chosen] if chosen else []) + rest

    # ------------------------------------------------------------- lifecycle
    async def _expand_discovery(self) -> None:
        """Replace the ``openrouter:free`` placeholder with live-catalog models."""
        if self._discover_at is None:
            return
        try:
            catalog = await _http_get_json(
                self.bases["openrouter"].rstrip("/") + "/models", timeout=20,
                api_key=self.keys["openrouter"],
            )
            found = discover_free_models(catalog)
        except Exception as exc:  # noqa: BLE001 - fall back to the known list
            log.warning("OpenRouter free-model discovery failed (%s); using fallbacks.", exc)
            found = []
        if not found:
            found = list(FALLBACK_OPENROUTER)
        specs = [ModelSpec("openrouter", m) for m in found]
        specs = [s for s in specs if s not in self.models]
        self.models[self._discover_at:self._discover_at] = specs
        self._discover_at = None
        chosen = self._resolve(self._preferred) if self._preferred else None
        default = chosen or (self.models[0] if self.models else None)
        self.model = default.key if default else None

    async def connect(self, resume: str | None = None) -> None:
        await self._expand_discovery()
        self._history = self._load_history()
        log.info("FreeBrain ready (models=%s, selected=%s, history=%d messages)",
                 [s.key for s in self.models], self.model, len(self._history))

    async def disconnect(self) -> None:
        return

    async def reset(self) -> None:
        self._history = []
        self.session_file.unlink(missing_ok=True)

    @property
    def session_id(self) -> str | None:
        return "chat" if self._history else None

    def _load_history(self) -> list[dict[str, str]]:
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        return [
            {"role": m["role"], "content": m["content"]} for m in data
            if isinstance(m, dict) and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
        ]

    def _save_history(self) -> None:
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.session_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._history, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.session_file)
        except OSError as exc:
            log.warning("Could not persist free chat history: %s", exc)

    def _trim_history(self) -> None:
        while len(self._history) > 2 and sum(len(m["content"]) for m in self._history) > self.history_chars:
            del self._history[:2]
        if self._history and self._history[0]["role"] != "user":
            del self._history[0]

    # ----------------------------------------------------------------- status
    async def status(self, *, force_refresh: bool = False) -> dict[str, Any]:
        return self.status_snapshot()

    def status_snapshot(self) -> dict[str, Any]:
        """Synchronous status: key state, per-model availability and budgets."""
        lines = []
        keys = ", ".join(f"{p} {'✓' if self.keys.get(p) else '✗ no key'}" for p in PROVIDERS)
        lines.append(f"Keys: {keys}")
        for spec in self.models:
            wait, reason = self.limiter.availability(spec)
            state = f"{reason}, back in {format_wait(wait)}" if wait > 0 else "ready"
            lines.append(f"{'●' if spec.key == self.model else '○'} {spec.key}: {state}")
        for provider in PROVIDERS:
            if not any(s.provider == provider for s in self.models):
                continue
            snap = self.limiter.snapshot(provider)
            minute = f"{snap['minute_used']}/{snap['minute_cap']} per min" if snap["minute_cap"] else \
                f"{snap['minute_used']} in the last min"
            day = f"{snap['day_used']}/{snap['day_cap']} today" if snap["day_cap"] else \
                f"{snap['day_used']} today (no daily cap set)"
            lines.append(f"{provider}: {minute} · {day}")
        if self._discover_at is not None:
            lines.append("openrouter:free: models are discovered when the brain starts")
        lines.extend(f"unavailable — {reason}" for reason in self.unavailable)
        return {
            "brain": self.name, "model": self.model or "none", "session_id": self.session_id,
            "usage": None, "usage_summary": lines,
        }

    # ------------------------------------------------------------------- chat
    async def _admit(self, spec: ModelSpec) -> str | None:
        """OpenRouter only: the live catalog must still price the model at zero."""
        if spec.provider != "openrouter":
            return None
        if spec.model not in self._admitted:
            try:
                catalog = await _http_get_json(
                    self.bases["openrouter"].rstrip("/") + "/models",
                    timeout=30, api_key=self.keys["openrouter"],
                )
                validate_free_model(catalog, spec.model, require_tools=False)
                self._admitted[spec.model] = None
            except Exception as exc:  # noqa: BLE001 - fail closed on any doubt
                self._admitted[spec.model] = f"not admitted as free: {exc}"
        return self._admitted[spec.model]

    def _payload(self, spec: ModelSpec, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": spec.model, "messages": messages, "temperature": 0.7,
            "max_tokens": self.max_tokens,
        }
        if spec.provider == "nvidia":
            override = dict(_NVIDIA_MODEL_PAYLOAD_OVERRIDES.get(spec.model.lower(), {}))
            override["max_tokens"] = min(int(override.get("max_tokens", self.max_tokens)), self.max_tokens)
            payload.update(override)
        else:
            payload["provider"] = free_provider_policy()
        return payload

    @staticmethod
    def _text_of(body: Any) -> str:
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return content.strip() if isinstance(content, str) else ""

    def _note_rate_headers(self, spec: ModelSpec, headers: dict[str, str]) -> None:
        """Back off proactively when the provider says the budget is spent."""
        remaining = headers.get("x-ratelimit-remaining-requests")
        if remaining is not None and str(remaining).strip() == "0":
            reset = _parse_duration(headers.get("x-ratelimit-reset-requests")) or 60.0
            self.limiter.cool_down(spec.key, min(reset, 3600.0))

    async def _try(self, spec: ModelSpec, messages: list[dict[str, str]]) -> tuple[str | None, str]:
        """(reply, why-not). Records usage and cooldowns as a side effect."""
        wait, reason = self.limiter.availability(spec)
        if wait > self.max_wait:
            return None, f"{reason}, back in {format_wait(wait)}"
        denied = await self._admit(spec)
        if denied:
            return None, denied
        if wait > 0:
            await self._sleep(wait)
        self.limiter.record(spec)
        url = self.bases[spec.provider].rstrip("/") + "/chat/completions"
        try:
            status, headers, body = await _post(
                url, self._payload(spec, messages), self.keys[spec.provider], self.timeout
            )
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            self.limiter.cool_down(spec.key, 30)
            return None, f"unreachable ({exc})"
        if status == 429:
            seconds = _parse_duration(headers.get("retry-after")) or 60.0
            self.limiter.cool_down(spec.key, min(seconds, 86_400.0))
            return None, f"rate limited, retry in {format_wait(seconds)}"
        if status in (401, 403):
            self.limiter.cool_down(spec.provider, 3600)
            return None, f"{spec.provider} rejected the API key (HTTP {status})"
        if status >= 500:
            self.limiter.cool_down(spec.key, 30)
            return None, f"provider error (HTTP {status})"
        if status != 200:
            self.limiter.cool_down(spec.key, 600)
            message = body.get("error", {}).get("message") if isinstance(body, dict) and \
                isinstance(body.get("error"), dict) else None
            return None, f"HTTP {status}" + (f": {str(message)[:120]}" if message else "")
        self._note_rate_headers(spec, headers)
        text = self._text_of(body)
        if not text:
            self.limiter.cool_down(spec.key, 30)
            return None, "empty reply"
        usage = body.get("usage") if isinstance(body, dict) else None
        self.last_turn_usage = dict(usage) if isinstance(usage, dict) else None
        return text, ""

    async def query(self, text: str) -> AsyncIterator[str]:
        self.last_turn_usage = None
        self.last_turn_cost_usd = None
        self.last_turn_outcome = "ok"
        if not self.models:
            self.last_turn_outcome = "error"
            yield "⚠️ No free model is usable.\n" + "\n".join(self.unavailable)
            return
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self._history,
                    {"role": "user", "content": text}]
        primary = self._order()[0]
        skipped: list[str] = []
        for spec in self._order():
            reply, why = await self._try(spec, messages)
            if reply is None:
                skipped.append(f"{spec.key} ({why})")
                continue
            self._history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
            self._trim_history()
            self._save_history()
            if spec != primary:
                reply += f"\n\n— answered by {spec.key}; {skipped[0]}"
            yield reply
            return
        self.last_turn_outcome = "error"
        waits = [self.limiter.availability(s)[0] for s in self.models]
        soonest = min(waits) if waits else 0
        hint = f" Next model free in about {format_wait(soonest)}." if soonest > 0 else ""
        yield "⚠️ No free model could answer right now:\n" + "\n".join(f"• {s}" for s in skipped) + hint
