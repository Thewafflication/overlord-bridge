# Local status and stop

Run from the source checkout or installed Python environment:

```powershell
python -m modules.local_control status --run-dir "C:\Users\jmwau\AppData\Local\Programs\Overlord\run"
python -m modules.local_control stop --run-dir "C:\Users\jmwau\AppData\Local\Programs\Overlord\run"
```

The installed entry point is `overlord-control`. Windows auto-detects the installed bridge when its control service is present; an explicit run directory identifies the intended instance. `--timeout` defaults to 30 seconds (maximum 60).

The `control_overlord` plugin tool accepts `action` (`status` or `stop`) and optional `run_dir`. Reinstall/update the repo-local Overlord plugin and open a new Codex chat to pick up its new tool. The CLI works immediately without plugin reload.

`status` returns a live acknowledgement with version, active-turn state, worker names and `idle`. `stop` follows Telegram `/stop`: cancel active workers and foreground turn, await cleanup, and keep the bridge/Telegram polling online. It returns `ok=true, stopped=true` only when idle. On `cleanup_pending`, poll status until idle before modifying the worker checkout. A timeout means no confirmed acknowledgement, not success. Non-success exits with code 2.

If discovery points to a process that has exited, clients report `control_unavailable` immediately instead of waiting for the full timeout. They also check for exit while waiting and clean up pending requests. A running or inaccessible PID does not prove bridge health: a matching protocol acknowledgement is still required. Windows uses a read-only process query; it never uses `os.kill(pid, 0)`.

The interface is a local file queue under `run/local-control`, intended for the same trusted local user who owns the bridge's console/dispatch files. It opens no network listener and reads no API keys. Per-request IDs correlate replies; bridge-instance IDs and deadlines reject stale/restarted/expired requests. Duplicate IDs do not execute twice. Only status and stop are accepted; arbitrary commands and messages are not part of this interface. Clients remove their request/reply files and the bridge expires leftover responses. Shutdown removes service discovery.

For the authorized monitor/fix/publish loop: inspect live status, stop a stalled run locally, require a confirmed idle state, then integrate/check/release. Never treat sending a request or terminating only a parent PID as evidence that cleanup finished.
