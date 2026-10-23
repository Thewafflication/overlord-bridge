"""Acknowledged local status/stop control; no credentials or model calls."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import time
import uuid
from typing import Awaitable, Callable

ACTIONS = {"status", "stop"}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def default_run_dir() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        installed = Path(os.environ["LOCALAPPDATA"]) / "Programs/Overlord/run"
        if (installed / "local-control/service.json").is_file():
            return installed
    return Path(__file__).resolve().parents[1] / "run"


def request(run_dir: Path, action: str, timeout: float = 30) -> dict:
    """Return only a matching live acknowledgement; a written file is not success."""
    if action not in ACTIONS or not math.isfinite(timeout) or not 0 < timeout <= 60:
        return {"ok": False, "error": "invalid_control_request"}
    root = Path(run_dir) / "local-control"
    try:
        service = json.loads((root / "service.json").read_text(encoding="utf-8"))
        instance = service["instance"]
        if service.get("protocol") != 1 or not isinstance(instance, str):
            raise ValueError("invalid service metadata")
    except (OSError, ValueError, KeyError, TypeError):
        return {"ok": False, "error": "control_unavailable", "message": "No compatible local control service; start an updated bridge."}
    identity = uuid.uuid4().hex
    inbox = root / "requests" / (identity + ".json")
    reply = root / "responses" / (identity + ".json")
    try:
        _write(inbox, {"id": identity, "instance": instance, "action": action,
                       "expires_at": time.time() + timeout})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = json.loads(reply.read_text(encoding="utf-8"))
                if (isinstance(result, dict) and result.get("id") == identity
                        and (result.get("instance") == instance or result.get("error") == "stale_bridge_instance")
                        and result.get("action") == action):
                    return result
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        return {"ok": False, "error": "control_timeout", "message": "No acknowledgement; stop is not confirmed."}
    except OSError as exc:
        return {"ok": False, "error": "control_io_error", "message": str(exc)}
    finally:
        for path in (inbox, reply):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


async def serve(run_dir: Path, handler: Callable[[str], Awaitable[dict]],
                shutdown: asyncio.Event, *, poll_interval: float = 0.2) -> None:
    root = Path(run_dir) / "local-control"
    inbox, outbox = root / "requests", root / "responses"
    inbox.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    instance = uuid.uuid4().hex
    completed = {}
    service_path = root / "service.json"
    _write(service_path, {"protocol": 1, "instance": instance, "pid": os.getpid(), "started_at": time.time()})
    try:
        while not shutdown.is_set():
            for path in sorted(inbox.glob("*.json"))[:16]:
                identity = path.stem
                try:
                    if uuid.UUID(hex=identity).hex != identity:
                        continue
                except ValueError:
                    continue
                action = ""
                try:
                    if path.stat().st_size > 4096:
                        raise ValueError("oversized request")
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("invalid request")
                    action = payload.get("action")
                    expiry = payload.get("expires_at")
                    if payload.get("instance") != instance:
                        result = {"ok": False, "error": "stale_bridge_instance"}
                    elif (not isinstance(expiry, (int, float)) or isinstance(expiry, bool)
                          or not math.isfinite(expiry) or not time.time() < expiry <= time.time() + 120):
                        result = {"ok": False, "error": "expired_control_request"}
                    elif payload.get("id") != identity or action not in ACTIONS:
                        result = {"ok": False, "error": "invalid_control_request"}
                    elif identity in completed:
                        result = completed[identity]
                    else:
                        result = await handler(action)
                except asyncio.CancelledError:
                    raise
                except (OSError, ValueError, TypeError):
                    result = {"ok": False, "error": "invalid_control_request"}
                except Exception:
                    result = {"ok": False, "error": "control_handler_failed"}
                completed[identity] = result
                if len(completed) > 256:
                    completed.pop(next(iter(completed)))
                try:
                    _write(outbox / path.name, {**result, "id": identity, "instance": instance, "action": action})
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            # Timed-out clients can leave replies behind; retain only five minutes.
            for path in outbox.glob("*.json"):
                try:
                    if uuid.UUID(hex=path.stem).hex == path.stem and time.time() - path.stat().st_mtime > 300:
                        path.unlink(missing_ok=True)
                except (OSError, ValueError):
                    pass
            await asyncio.sleep(poll_interval)
    finally:
        try:
            if json.loads(service_path.read_text(encoding="utf-8")).get("instance") == instance:
                service_path.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(ACTIONS))
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    result = request(args.run_dir or default_run_dir(), args.action, args.timeout)
    print(json.dumps(result))
    return 0 if result.get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
