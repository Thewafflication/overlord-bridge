# Shared Capabilities

This file is the living catalog of things Claude and Codex should both know
about in the Overlord setup. Keep it current when a new helper, service, or
workflow lands.

## Current Capabilities

- Free model pool: OpenRouter discovery includes up to sixteen live zero-priced chat models, with vendor diversity first and sibling models afterward. Gemini 3.5 Flash-Lite, 3.1 Flash-Lite, 2.5 Flash and 2.5 Flash-Lite are supported by free chat and the shared worker completion pool through Google's compatible endpoint. Configure a Google AI Studio key and explicitly enable Gemini in Settings > API keys; use a project without billing for free-tier usage. Paid projects can incur charges, and Overlord cannot inspect their billing tier. Provider-wide pacing and cooldowns remain active. Grok, ChatGPT and Claude free web plans do not grant free API usage; OpenAI GPT-OSS is available through NVIDIA. See [1.0.60](docs/releases/1.0.60.md).

- Local worker control: `python -m modules.local_control status|stop --run-dir <bridge-run-directory>` (or installed `overlord-control`) reads live task state or uses the same cancellation path as Telegram `/stop`, without a model call or credentials. The `control_overlord` MCP tool exposes the same interface. Stop succeeds only when active turn and worker cleanup are confirmed idle; timeout or `cleanup_pending` is not confirmation. The bridge stays running. Requests carry an instance ID, unique request ID and deadline so stale/expired requests cannot stop a later bridge. In owner-authorized monitoring/fix sessions, use this to stop and verify locally instead of requesting a manual Telegram round trip. See [local control](docs/local-control.md).

- Context monitoring: `/context` shows the latest fresh session/model-matched
  observation and the warning/automatic-compaction settings. Configure
  `OVERLORD_CONTEXT_WARN_PERCENT` (75), `OVERLORD_CONTEXT_COMPACT_PERCENT` (85)
  and `OVERLORD_CONTEXT_AUTO_COMPACT` (off unless enabled). Warnings and attempts
  are deduplicated; automatic compaction runs between turns after a checkpoint,
  defers for approvals/questions, and leaves session IDs and grants intact.
  Claude uses opted-in native snapshots; Codex uses last-request usage rather
  than cumulative billing; free mode monitors its explicitly labelled local
  history budget and compacts with a tool-free summary plus transcript backup.
  See [context monitoring](docs/context-monitoring.md) for limits and validation.

- Shared engine context: Claude, Codex and free mode receive the canonical
  `AGENTS.md` selected by `OVERLORD_INSTRUCTIONS_FILE` (or the bridge copy).
  Durable preferences, project notes and latest worker reports live locally in
  `%LOCALAPPDATA%/Overlord/state/shared-memory.json` on Windows (outside the
  replaceable install) or `run/shared-memory.json` elsewhere, and are supplied fresh on each owner
  turn. Free chat has a `shared_memory` tool; native engines use the same store
  through `modules/shared_memory.py`. Explicit owner requests save, update or
  forget notes. `/new` clears conversation, not durable memory. Worker claims
  remain labelled and bounded. See [shared context](docs/shared-context.md).

- Free-mode Telegram chat defaults to brief, context-relevant answers. Successful
  model fallback is recorded in local logging without appending provider errors
  to the conversation; failures that prevent an answer remain visible. Free chat
  records token usage for /tokens without an automatic per-reply footer. New worker
  reports enter persisted chat context, labelled as worker-reported claims rather
  than independently verified results. Reply guidance accompanies the latest
  prompt so older verbose conversation does not set the default response style.
  Text replies longer than 80 words receive one tool-free model editing pass
  to remove repetition and unsolicited offers while preserving requested detail.
  Editing has a 30-second deadline, uses the same free-model admission/budgets,
  and records both calls' token usage. If editing is unavailable, the original
  answer is delivered. Short replies and tool results bypass editing.

- Worker progress: free/local-model tool loops show the task, concrete upcoming
  file or command actions, model-authored progress notes, and actual tool results
  in Telegram and the console log. Routine file activity is batched at roughly
  eight-second intervals; writes and commands announce their next action
  immediately. Updates are bounded and command-display secret redaction applies.

- Free project workers continue until the model completes the task or the run is
  cancelled, with no default agent-step cap. `OVERLORD_FREE_WORK_STEPS=0` disables
  the cap; a positive value sets an optional limit. Explicit cap exhaustion is
  reported as incomplete rather than successful completion. Provider usage limits,
  request failures, tool approval rules and duplicate-call protections still apply.

- Clearer output and collapsible logs: the Windows console shows a short latest
  activity summary and a collapsed detailed-log pane that keeps collecting while
  hidden. Telegram renders explicitly labelled `log`/`output` fenced blocks as
  expandable quotes. Findings and instructions stay visible; token counters and
  fallback diagnostics have short summaries with expandable details. Brain turns
  are delivered together on completion; partial text is preserved on interruption.

- Permission levels: Settings → Permissions provides a persisted `ask`, `safe`
  (default), or `full` bridge level, stored in `OVERLORD_PERMISSION_LEVEL`.
  `ask` prompts for actions; `safe` auto-approves the routine command allowlist;
  configured `full` auto-approves bridge actions until changed. Off-limits and
  native engine restrictions still apply. `/permissions level ask|safe` changes
  the running level and clears grants; `/permissions full 10` gives a temporary
  full-access window. Explicit levels override the legacy auto-approve setting.

- Routine command approval policy: enabled by default in the shared permission
  gate for Claude, Codex and free-worker approval requests. It accepts a bounded
  set of Git inspection commands and local Make/pytest/npm/CMake/CTest build and
  test commands inside the supplied workspace. Build recipes are trusted project
  code. Unknown invocations, publishing/install/destructive operations, shell
  chaining, expansions, redirection and paths outside the workspace still prompt.
  Decisions are audited and off-limits checks run first. `/permissions safe off`
  disables the policy for the running bridge; `safe on` restores it. Timed access
  and exact-action grants remain separate controls.

- Runtime host context: all bridge brains and project workers receive the actual
  host platform. Windows owner instructions use PowerShell and Windows paths;
  local/free worker shell commands account for their cmd.exe execution surface.
  Linux documentation examples or old conversation cannot establish the host OS.

- Timed full access: `/permissions full [minutes]` grants bridge approval access
  for a bounded window (default 10 minutes, range 1–1440), including free-worker
  writes and commands. Pending requests are released; every subsequent request
  checks a monotonic deadline. Off-limits rules and native sandbox limits remain.
  `/permissions` shows remaining time; `/permissions revoke all`, `/new`, or a
  process restart clears the grant. Expiry does not cancel commands already started.

- Free-brain natural project requests: Telegram chat offers an LLM tool to
  dispatch the existing free-model worker in a configured local project. Friendly
  project descriptions are resolved against the listed folder names; ambiguous
  requests ask for clarification. Reviews request file/line findings without edits.
  `/work` remains available for explicit dispatch and worker status/stop.

- Windows GUI settings: the tray and console **Settings…** button opens tabs for
  API keys, individual projects / project parent folders, and bridge / Claude-edit /
  free-worker approval settings. Save reloads these into the running bridge.
  Projects are stored as JSON arrays in `OVERLORD_PROJECT_FOLDERS` and
  `OVERLORD_PROJECTS_ROOTS`. The live console highlights native Codex command
  events, Claude SDK Bash hooks, shared Claude Telegram-turn transcripts, and
  free/local/NVIDIA worker shell execution,
  with command, working folder, completion status and available exit codes.

- `voice_gateway`: place and manage phone calls, send DTMF, listen to real
  people with local Whisper STT, and speak responses through Azure TTS or
  ElevenLabs. Live as MCP tools (`hfp_status`, `lookup_contact`, `place_call`)
  via the `voice-gateway` plugin in the `nova-local` marketplace (added
  2026-07-11) — previously the engine was CLI-only, so no brain could
  actually place a call even though it worked; now it's callable directly.
- `nova-local` plugin marketplace (`.claude-plugin/marketplace.json`, rooted
  in this repo): the landing spot for every future local MCP server. A raw
  `~/.claude.json` MCP entry only takes effect at session start (a restart
  per new tool — expensive against a 5-hour cap window); a plugin-provided
  MCP server picks up with `/reload-plugins` instead, no restart. Each plugin
  lives at `plugins/<name>/.claude-plugin/plugin.json` declaring its own
  `mcpServers` block. Install once, then `/reload-plugins` after future
  additions. Current plugins: `ytmusic-dj`, `voice-gateway`.
- `ytmusic-dj`: Nova's AI DJ for YouTube Music. Tools: `search_tracks`,
  `create_playlist`, `analyze_playlist`, `list_ai_playlists`,
  `get_ai_playlist`, `edit_ai_playlist`, `reorder_ai_playlist`,
  `delete_ai_playlist`, `whoami`. Resolves a seed playlist/track to real
  videoIds and creates/edits playlists in Ben's BENformation channel;
  edit/delete are guardrailed to playlists this tool itself created. Wired
  via the `nova-local` marketplace.
- Telegram phone bridge: one owner-gated Overlord conversation reachable from
  Telegram and the terminal, with shared session sync between them.
- `overlord` launcher: resumes the current shared Overlord thread in the
  terminal, matching the active brain.
- `overlord`: **one brain, two microphones — Telegram and the terminal are the same
  live conversation. This is the DEFAULT; no flag needed.** `overlord --no-shared`
  forces the old plain-resume path, and any unexpected condition falls back to it
  automatically. Runs Ben's pin through Claude Code's local
  background-job daemon (`claude --bg`, `claude attach <id>`) instead of a plain
  `claude --resume` (mechanism found 2026-07-13, see
  `research/one_brain_poc/NOTES.md`). Unlike plain `--resume` — where a second
  live process silently forks — a `--bg` job accepts MULTIPLE attached clients
  at once, mirroring input live, with a single unforked transcript.
  - Ben's half: `overlord` creates (or reuses) the job and attaches his terminal to
    it. He gets the **real Claude Code TUI** — statusline, slash
    commands, permission footer, plan mode — because `attach` is the native
    client, not a homegrown pipe. The job is tracked in `.session.claude.job`
    (`<job-id>:<live-session-id>`) so repeat runs reuse it. Note `claude --bg
    --resume` does NOT resume in place — it starts a NEW session id and freezes the
    old transcript — so the launcher re-pins to the job's live id. A running job is
    also findable from the pin alone via the roster, so a lost sidecar is survivable.
  - The bridge's half (`modules/shared_job.py`): when a live shared job exists,
    a Telegram turn is typed straight into it and the reply is read back from the
    session JSONL. So a message sent from bed lands in the conversation his
    terminal is showing, and is still there in the morning. No live shared job →
    the bridge silently uses the ordinary per-turn SDK path (Design B), so plain
    `overlord` behaves exactly as before.
  - Worker reports (`shared_job.notify`) are injected the same way, so a
    completion shows up in Telegram AND the live terminal automatically — no
    per-dispatch arming, no tmux launcher wrap, no Monitor polling.
  - **Guarded:** injection types into a real pty, so it refuses to type while Ben
    has a half-written message sitting at the prompt (its Enter would submit his
    sentence). Idleness is judged by rendering the attached frame through `pyte`
    and reading the bottom-most prompt line. A refusal degrades to Telegram-only
    delivery — never a mangled terminal, never a lost message.
  - **Permissions caveat:** an injected turn runs inside the job's own `claude`
    process, so its tool calls follow that process's permission settings and do
    NOT raise the bridge's Telegram Allow/Deny prompt (the gate still guards the
    SDK fall-back path). Consistent with Ben's `defaultMode: bypassPermissions`,
    but worth knowing before trusting it with something destructive.
  - Falls back to today's exact `claude --resume` on any unexpected condition
    (job creation fails, pin already held by a live interactive session, etc).
- `overlord status` (alias `overlord health`): one command that re-grounds a
  session on WHO it is (the Overlord) and runs a single bridge health sweep —
  active brain, service state, pinned session, Codex shared socket, and pending
  dispatch files. Launches no brain; safe to run any time. Use it instead of
  hand-running five separate checks.
- Brain swap: Overlord can run on Claude or Codex, selected by `OVERLORD_BRAIN`.
- Allow/Deny approvals: actions outside the pre-approved set are surfaced to
  Telegram with operator prompts and time out into denial.
- Worker dispatch from Telegram: the bridge can spawn named workers into
  project folders and report results back in the thread.
- `overlord-email`: sends mail through Gmail SMTP and supports file attachments
  with `--attach`. It reads `GMAIL_USER` and `GMAIL_APP_PASSWORD` from
  `overlord-bridge/.env`.
- `overlord` Codex plugin / MCP surface: exposes shared capabilities as
  lazy-loadable tools (`list_overlord_capabilities`,
  `find_overlord_capabilities`, `overlord_status`, `send_overlord_email`, and
  `dispatch_overlord_worker`). The source lives in `plugins/overlord`, with a
  repo-local marketplace at `.agents/plugins/marketplace.json`; reinstall with
  `codex plugin add overlord@personal` after plugin changes. Claude can use the
  same brain-neutral stdio MCP server by registering the command from
  `plugins/overlord/.mcp.json`. New Codex threads pick up the lazy-loaded tools.
- Worker dispatch: create a JSON file in `overlord-bridge/dispatch/` and the
  bridge will run a named worker in a project folder.
- Worker reports: terminal worker completions/failures/timeouts are pushed to
  Telegram, written to `worker_reports/events.jsonl` and
  `worker_reports/latest/<worker>.json`, and, for the active Codex Overlord
  brain, appended to the same app-server thread via `thread/inject_items`.
  `WORKER_REPORT_VISIBLE_TURN=true` can additionally start a tagged visible
  assistant status turn in the active bridge Codex app-server thread. Live Codex
  TUI visibility requires the shared Unix-socket path: bridge direct WebSocket to
  `codex app-server --listen unix://...` and terminal `codex --remote
  unix://... resume <thread>` through the `overlord` launcher.
- CLI-side worker-report surfacing (dual delivery: Telegram **and** the live
  terminal Overlord session, not a replacement for either). **The tmux launcher
  wrap was removed from `overlord` on 2026-07-05** — Ben rejected it
  (2026-07-01) and it now just execs `claude` directly, no `overlord-<brain>`
  tmux session, no split tail pane. Historical context: the launcher used to
  run the brain in tmux pane 0 with pane 1 tailing
  `worker_reports/cli_feed.log`, plus an opt-in `WORKER_REPORT_TERMINAL_INJECT`
  path that `tmux send-keys`-typed reports into the live brain pane. That whole
  approach is gone from the launcher. The bridge-side feed append
  (`WORKER_REPORT_CLI_FEED`, `modules/cli_notify.py`) still exists and is
  harmless, but nothing consumes it via tmux anymore.
  The actual live practice: the interactive Claude Overlord session self-arms a
  `Monitor`/background watch on `worker_reports/events.jsonl` (seeded from the
  current line count, NOT `tail -F -n0` — this box's `tail` is uutils
  coreutils, which doesn't honor `-n0` and dumps the whole backlog) and relays
  each terminal-status line inline as a plain human-readable turn, no raw JSON.
  Needs zero bridge changes; it's a per-session runtime practice, not
  infrastructure. Reporting template Ben set: `TIMESTAMP / Worker: <name> /
  Completed task: <task> / Result: <result>` — verify the actual artifact
  before filling in Result, a worker's own final line is often just "Done."
- Trusted Codex workers can be launched unattended per project with
  `"approval_policy":"never"` and `"sandbox":"workspace-write"` in the
  dispatch JSON. **Codex is intermittent-but-credited (updated 2026-07-15), not
  retired** — it's polled by the engine gas gauge and dispatchable as a fallback
  *when the gauge says it's up* (see the "Engine gas gauge" entry; kill-switch
  `OVERLORD_ENGINE_CODEX_DISABLED`). Old roster codex sessions are still dead —
  re-hire with a fresh uuid, don't resume the old id.
- Local agent workers can be launched with `"brain":"local-agent"` and a model
  alias: `"qwen3-coder-next"` (-> `openai/Qwen3-Coder-Next`, on-demand local
  `llama.cpp`/`llama-server`) or `"qwen2.5-coder-14b"` (->
  `ollama_chat/qwen2.5-coder:14b`). This is the local-model Codex/Claude-style
  worker path: the bridge gives the model tools to list files, read/write
  project files, run commands in the worker folder, feed results back, continue
  looping, validate, and commit. `files` is optional and only a starting hint —
  the local agent can inspect the project itself and loop one file at a time
  without a preselected list. The bridge pins a fixed context window by default
  (`OVERLORD_WORKER_LOCAL_AGENT_CONTEXT_TOKENS`, default `256000`, retry floor
  `OVERLORD_WORKER_LOCAL_AGENT_MIN_CONTEXT_TOKENS`, default `2048`) with
  model-specific hard caps after alias resolution; `qwen3-coder-next` is capped
  at `256000`. For the llama.cpp-backed alias the cap becomes the per-job
  `llama-server --ctx-size`; the bridge starts that server only for the worker
  run and stops it after, using `--no-mmap`, `--cache-ram 0`, q8 KV cache, and
  configurable MoE CPU offload. For the Ollama alias the cap becomes `num_ctx`,
  retrying once at a smaller cap if Ollama reports insufficient memory. Local
  workers are currently one-shot, not persistent resumable sessions. Treat this
  model as rough but free: a last-resort fit for small, contained tasks, and
  sometimes acceptable for a narrow large-single-file edit because the 256k
  context gives it enough room to function. Do not hand it broad, ambiguous, or
  high-judgment work.
- NVIDIA NIM cloud workers can be launched with `"brain":"nvidia"` (aliases
  `nim`, `nvidia-nim`): the same tool-loop harness as `local-agent`, pointed at
  NVIDIA's free OpenAI-compatible endpoint (`integrate.api.nvidia.com/v1`) —
  big frontier-adjacent models with huge contexts and zero local VRAM cost.
  Requires `OVERLORD_WORKER_NVIDIA_API_KEY` in `.env`. Aliases live in
  `modules/workers.py` `_NVIDIA_MODEL_ALIASES`; unrecognized model strings
  pass through verbatim, so any id from `GET /v1/models` can be tested.
  Human free-preview catalog, sorted by popularity:
  `https://build.nvidia.com/models?filters=nimType%3Anim_type_preview&orderBy=weightPopular%3ADESC`.
  Machine-readable availability for Ben's key:
  `GET https://integrate.api.nvidia.com/v1/models` with
  `Authorization: Bearer $OVERLORD_WORKER_NVIDIA_API_KEY` (cached for normal gas
  checks; default TTL 300s). Per-model sampling and `chat_template_kwargs`
  tweaks are copied from the NVIDIA Build prototype snippets and applied
  automatically (`_NVIDIA_MODEL_PAYLOAD_OVERRIDES`). 429/5xx are retried with
  backoff.
  Like local-agent, these are one-shot workers, not resumable sessions;
  `model` and `files` hints work the same way.
- **NVIDIA model selection — which model for which worker task.** If unsure,
  **2026-10-11 update:** the default and `gpt-oss` alias now use
  `openai/gpt-oss-20b`; the 120B endpoint has retired. The free pool uses
  GPT-OSS 20B, Nemotron 3 Super and Nemotron 3.5 Lightning; all three passed
  live chat and tool-call checks with the installed key. The July rankings
  below are historical; Mistral Small 4 and Llama 3.3 also returned HTTP 410.
  For the original July qualification,
  omit `model` entirely: the default is `gpt-oss`
  (`openai/gpt-oss-120b`). In the 2026-07-16 same-prompt smoke matrix it was the
  fastest practical coding answer (7.2s) and the only quick NVIDIA model whose
  generated asserts plus external verifier passed the merge-ranges prompt.
  Current practical rank:
  - `gpt-oss` — DEFAULT for automatic NVIDIA worker dispatch. Best current pick
    for small/medium coding, review/analysis, structured extraction, and
    low-risk reasoning where a slightly odd writing style is acceptable.
  - `mistral` — best writing-heavy automatic fallback. It was close in the
    creative smoke and very fast (5.7s) on code, but missed the stricter
    integer-adjacent "touching ranges" interpretation in the coding smoke.
  - `nemotron` — fast NVIDIA-owned fallback. Latency was practical (19.6s), but
    it also missed integer-adjacent touching in the coding smoke.
  - `minimax` / `minimax-m3` and `minimax-m2.7` — manual-only. Minimax M3's code
    body passed the external verifier but emitted self-failing asserts; M2.7 was
    slower and missed integer-adjacent touching. Neither is trusted as a
    coding/tool worker yet.
  - `qwen3-next` / `qwen-next` — keep as a visible fallback and prefer it over
    old Qwen 3.5 variants, but do not auto-prefer it when gpt-oss/Mistral are
    available: the coding function passed external checks, but its own asserts
    were wrong and the run took 3m27s.
  - `llama` — last automatic NVIDIA fallback only. The coding function passed
    external checks, but its own asserts were wrong and the run took 10m06s.
  - `kimi` — broken on the live NVIDIA worker path: HTTP 404 on 2026-07-16.
  - `deepseek` — manual-only despite strong creative output quality. It took
    15m19s on the limerick smoke, then 15m22s and crashed with HTTP 504 on the
    tiny coding smoke, so it is not viable for routine worker dispatch.
  - `qwen3.5` (122B), `qwen3.5-397b`, or `mistral-large-3` — visible/manual-test
    fallbacks for experimentation; do not prefer them for routine dispatches.
    `qwen3.5-397b` is the biggest brain, but frequently queues/times out on the
    free tier; only use it where a failed/slow run is acceptable.
  - AVOID as auto-selected workers: `kimi` / `kimi-k2.6` (listed in the catalog,
    but live worker call returned HTTP 404 on 2026-07-16), `minimax` /
    `minimax-m3`, `minimax-m2.7`, `deepseek` / `deepseek-v4-pro`, and
    `deepseek-flash`. Wired for explicit experimentation only.
  Tool-calling verified live 2026-07-02 for: deepseek-v4-pro, qwen3-next,
  qwen3.5-122b, gpt-oss-120b, mistral-large-3, nemotron-3-super. Kimi was
  previously believed usable, but is currently disabled for auto-routing.
- **Worker brain selection** (for Overlords unsure which brain to dispatch):
  prefer calling the **`recommend_engine`** MCP tool, or pass `brain:"auto"` /
  `auto_route:true` to `dispatch_overlord_worker`. It checks live gas and job
  fit before spending Ben's premium sessions. The manual policy it encodes:
  `claude` for high-stakes, broad multi-file, ambiguous, or high-judgment work;
  if Claude is capped and Codex has gas, use `codex` as the next-smartest brain.
  If the job is too hard for NVIDIA/local and Codex is unavailable, **defer
  until Claude resets** instead of creating Claude cleanup work. `nvidia`
  gpt-oss is the current free automatic pick for medium, well-specified coding,
  debugging, and review tasks where verification is possible; use Mistral first
  for writing-heavy chores. Do not overreach on vague architecture or
  high-judgment tasks. `local-agent` is free and local, but rough: last resort
  for small contained tasks or a narrow large-single-file edit, not broad work.
  Proven 2026-07-16 dispatcher suitability matrix for low/medium coding chores:
  `gpt-oss` first; `mistral`; `nemotron`; `local-agent` as the free/local last
  resort; `minimax` manual/test-only; `qwen3-next`; `minimax-m2.7` manual-only;
  `llama`; `kimi` broken; `deepseek` unusable on NVIDIA free-tier dispatch.
- **Engine gas gauge + preference router** (built 2026-07-15, updated
  2026-07-16): before dispatch,
  know per engine whether it's usable *right now*. Three MCP tools plus a CLI:
  - `engine_gas_gauge` — probes `claude` (live 5-hour session + 7-day weekly
    usage caps → `gas`/`weekly_gas`), `nvidia` (key + cached `/models`
    reachability, plus a bounded popular-model watchlist: Nemotron, Qwen3-Next,
    Mistral, Llama, gpt-oss, DeepSeek, Kimi, MiniMax. Normal gas does **not**
    POST-test every model; per-model `gas` is synthetic from catalog presence
    plus recent worker/smoke reports: `100` means listed with no recent worker
    failure; `0` means missing, broken, recently rate-limited, or queued/timed
    out),
    `codex` (ChatGPT backend reachable + `~/.codex/auth.json` authed, layered
    with real 5-hour/weekly plan usage % parsed from the newest
    `~/.codex/sessions/**/rollout-*.jsonl`'s `rate_limits` entry — windows are
    matched by `window_minutes`, 300=5h/10080=weekly, not by primary/secondary
    position, since Codex has changed which one it populates; falls back to
    reachable+authed only when no usage entry is found yet), `local-agent`
    (llama.cpp/Ollama live, or startable). Each: `{usable, gas,
    weekly_gas, state, reason}`; state ∈
    `ready|degraded|out_of_gas|offline|unavailable`. Only `ready` is
    dispatchable; degraded/offline/out-of-gas entries are diagnostics, not
    candidates. Cloud engines are marked `degraded` from recent rate-limit/usage
    failures in `worker_reports/events.jsonl`.
  - `engine_gas_dashboard` — same readable first-page dashboard as
    `overlord gas`, returned as plain text for Codex/Claude. Use it when Ben
    asks for "gas", "/gas", current limits, or engine availability; paste the
    full dashboard output unless he asks for analysis.
  - `recommend_engine` — job-fit, gas, and cost-aware ranking. Decisions are
    `dispatch_now`, `dispatch_with_handoff` (use reserve Claude for Claude-shaped
    work), `defer_until_reset`, or `blocked`. Hints (`stakes`, `multi_file`,
    `ambiguous`, `needs_judgment`, `must_stay_local`, `writing_heavy`,
    `review_or_analysis`, `small_chore`, `context_size`, `prefer`) choose the
    suitability tier; for an `nvidia` pick it also chooses the model.
  - `dispatch_overlord_worker` gas guard: dispatching to a non-ready brain
    returns `{blocked:true, recommended:…}` WITHOUT writing the dispatch (so you
    re-dispatch to the suggested engine); `force=true` overrides, and the chosen
    brain's gauge entry is recorded in the dispatch `routing` block. With
    `brain:"auto"` / `auto_route:true`, the dispatch tool follows
    `recommend_engine`: it may write a normal dispatch, write a handoff + arm a
    resume timer for reserve-Claude work, or schedule Claude after reset instead
    of dispatching an unsuitable fallback.
    This is the backstop against the 2026-07-14 "dispatched Claude while out of
    gas" mistake. Config: `OVERLORD_CLAUDE_HANDOFF_USAGE_PERCENT` (default 85,
    shared with `~/.claude/hooks/near-limit-handoff.sh`; router reserve gas is
    `100 - this value`), `OVERLORD_ENGINE_CLAUDE_GAS_FLOOR` (default 5),
    `OVERLORD_ENGINE_CODEX_GAS_FLOOR` (default 5), `OVERLORD_ENGINE_CODEX_DISABLED`
    kill-switch. The old `CLAUDE_NEAR_LIMIT_PERCENT` is still accepted as a
    fallback by the hook/router, but prefer the Overlord env name.
  - `overlord gas` — terminal table of the gauge (no brain launched, like
    `overlord status`); `overlord gas --json` for the raw payload.
- `fetch_relay` (`modules/fetch_relay.py`, own service `overlord-fetch-relay`):
  a localhost-only (127.0.0.1) HTTP endpoint that renders pages with a real
  headless Chromium (Playwright + `playwright-stealth`) instead of a plain
  HTTP client, for sites the brains' own WebFetch tool domain-blocks (e.g.
  reddit.com) or that bot-wall plain curl by fingerprinting a missing JS
  engine. Call it with Bash: `curl -s
  'http://127.0.0.1:8791/fetch?url=<url>'` (default port 8791, overridable via
  `FETCH_RELAY_PORT`). Query params: `url` (required, must be `http(s)://`),
  `format=text|html|json` (default `text`, `json` also includes `title`,
  `final_url`, `status`, and optionally `html` with `include_html=1`). Text is
  a readability extraction via `trafilatura`. Anonymous only — every request
  gets a fresh throwaway browser context, no cookies/login/credential storage,
  matching Ben not using a Reddit account on this desktop. Safeguards: refuses
  to bind anything but loopback (can't become an open proxy), rejects
  non-http(s) URLs, and bounds every fetch with a hard timeout
  (`FETCH_RELAY_TIMEOUT_SECONDS`, default 20s). Runs continuously via the
  `overlord-fetch-relay.service` systemd --user unit (same install pattern as
  `overlord-bridge.service`: `cp overlord-fetch-relay.service
  ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl
  --user enable --now overlord-fetch-relay`). One-time setup after `pip
  install -r requirements.txt`: `playwright install chromium`.
- New project folders should be git repositories by default unless Ben says
  otherwise.
- The shared Overlord instructions are rooted in `AGENTS.md`, and Claude uses
  the `~/CLAUDE.md` / `~/.claude/CLAUDE.md` symlinks that point to it.
- `schedule_resume_after_cap`: Overlord MCP tool (in `plugins/overlord`) that
  auto-resumes a paused/handoff job shortly AFTER the Anthropic usage cap
  resets, so Ben never has to log in at 3am just to say "keep going". It reads
  the reset time itself from the live usage source (the same
  `api.anthropic.com/api/oauth/usage` call ccstatusline + the near-limit hook
  use; prefers the fresh `~/.cache/near-limit-handoff/usage.json`), computes
  reset + `after_reset_seconds` (default 300 = 5 min), and registers a DURABLE
  `systemd --user` transient timer. At fire time `resume_fire.py` drops a bridge
  dispatch (a fresh-session worker) so the persistent bridge runs the
  continuation and reports to Telegram — this SURVIVES the very session that hit
  the cap (unlike the harness `CronCreate`, which is session-only/in-memory).
  Args: `folder` + `task` (tell the worker to read HANDOFF.md and commit before
  done); `cap` = `session` (5-hour, default) or `weekly` (7-day); optional
  `resume_at`/`delay_seconds` overrides. Companion `cap_status` reports both
  caps' utilization %% + reset times. Returns the timer unit + a `cancel_cmd`
  (`systemctl --user stop <unit>.timer`). Built 2026-07-09.

- `net_ssh`: Overlord MCP tool (in `plugins/overlord`) that lets the **Overlord
  only** (never a dispatched worker) reach machines on Ben's LAN over SSH to
  update open-source software or diagnose them. It is a HELD session, not a
  per-command reconnect: `action:"connect"` opens a persistent SSH ControlMaster
  socket (one auth via Ben's ssh-agent — no identity file, no password prompt),
  `action:"run"` runs commands inside that live session with no re-auth,
  `action:"close"` tears it down, `action:"status"` lists live connections.
  Sessions auto-close after 30m idle (`idle_timeout`); the socket lives under the
  private `run/ssh/`; every call appends to `net_ssh_audit.log`. Worker exclusion
  is by cwd — the tool runs only from the home root, and a worker's MCP server
  runs in its project folder. **Gateway rule (behavioral, in AGENTS.md):** if Ben
  tells you to reach a host that IS the approval; if you decide on your own you
  need a host he didn't send you to, ask him first and wait for a yes. Always
  report connect/close state clearly (🔗/🔌) so Ben always knows whether a door
  is open. Auth is ssh-agent only, so an unkeyed host just fails to connect.
  Built 2026-07-22. Registered in `~/.claude.json`, so a new tool appears only in
  a fresh Overlord session.

## Keep In Sync

- Update this file whenever a new helper or repeatable workflow becomes part of
  the Overlord toolkit.
- If a capability matters to Ben, mention it here before assuming either
  assistant will remember it on its own.

### Manual free OpenRouter workers

Dispatch with `brain: "openrouter"` and an exact tool-capable `model` ID ending in `:free`. Enable `OVERLORD_WORKER_OPENROUTER_ENABLED=1` and configure `OVERLORD_WORKER_OPENROUTER_API_KEY` in the bridge environment. This explicitly permits sending worker task and project context to OpenRouter providers. The bridge validates current catalog input/output prices before reading hinted files, and sends a zero-price provider ceiling with fallback disabled on every turn. Missing consent, keys, pricing, or tool support fails closed. Resume is rejected. The existing worker file/command restrictions apply. This manual pilot is not automatically routed or live-qualified; no provider calls were made during offline testing.

Provider contract: [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection).

### Automatic per-prompt model selection

Configure a local OpenAI-compatible classifier (for example an existing Ollama server) with `OVERLORD_ROUTER_MODEL` and `OVERLORD_ROUTER_API_BASE`, then set `OVERLORD_ROUTER_ENABLED=1`. The endpoint must be loopback HTTP. `OVERLORD_ROUTER_PROFILES` is JSON keyed by `claude` and `codex`; each entry has `model`, a capability/cost `description`, and `qualified: true` only after that exact model has been validated with the provider. Unqualified entries cannot be selected. No classifier model is downloaded or started automatically.

```json
{"claude":[{"model":"sonnet","description":"Lower-cost routine implementation and explanation","qualified":false},{"model":"opus","description":"Difficult design and high-stakes judgment","qualified":false}]}
```

The classifier interprets each prompt with up to eight recent dialogue entries (6,000 characters), chooses from the active provider's qualified list, and returns a validated model ID and reason. It has no tools, does not enter the persistent native conversation, and has a 12-second deadline. Invalid selections, outages, oversized prompts, or refused native model changes retain the current model; the user prompt is sent once. Native session IDs and permission grants are retained. Codex additionally intersects configured profiles with its visible native `model/list` catalog, using a five-second deadline and at most ten pages. Catalog failure retains the current model. A bundled/cached catalog does not prove account entitlement. Claude catalog discovery, gas-aware cross-provider routing, and a live routing evaluation set remain open.

`/model` shows routing state and the last decision. `/model <name>` sets a manual override for this bridge process; `/model auto` restores automatic selection after configuration. Routing decisions do not overwrite the saved manual model. A live shared Claude terminal retains its own model because its transport does not expose per-turn model selection. No paid classifier calls or live qualification were performed for this increment.

Multi-question requests show progress and require review before submitting the complete set. Use the review buttons to edit a selected answer or cancel all answers. Single-question requests retain direct submission. Cancellation or timeout during a set returns no partial answers. Invalid, duplicate, or oversized sets are rejected instead of silently dropping questions; requests support at most four questions. Pending native requests are not restored after a bridge restart.

Permission decisions are recorded locally in `run/permissions.jsonl`, with one retained `.previous` file and a 256 KiB cap per file. Records contain UTC time, owner ID, decision source and a SHA-256 action identity; they omit command arguments, paths and conversation text. `/permissions` reports audit health. A failed audit write denies approvals (including configured auto-approval and reused grants); revocation and denial still take effect if storage is unavailable. The audit remains local and is not a complete audit of shared-terminal or worker side effects.

### Free worker command and file tools

Project workers expose `run_command` with an optional `shell: "powershell"` on Windows (default remains cmd.exe), plus `run_python` with a multiline `code` string using the bridge interpreter. Both execution tools use worker command restrictions and free-mode command approval. `read_file` accepts 1-based `start_line` and `line_count` for targeted source inspection without shell pipelines; omitted ranges retain the bounded tail behavior.


Free workers now prefer an existing project `.venv` for Python execution and command PATH (bridge interpreter fallback); their startup context names it. `search_file` searches a named allowed text file for a case-insensitive literal `query`, returning bounded matches with line numbers. Unknown tool errors include supported tool names. Empty responses receive two continuation attempts, then produce an incomplete result; final outcomes are logged with bounded, redacted text.


Worker `list_files` accepts `path` (project-relative directory) and `pattern` (filename glob, e.g. `*.py`). Generated/dependency/secret/linked directories are pruned during traversal. Worker command timeouts clean up the owned Windows process tree or POSIX process group before a bounded output drain; timeout cleanup is logged and buffered output is retained when pipes close.


Background workers now share Telegram typing ownership with foreground turns. Typing refreshes every four seconds and wakes after outbound messages; the final operation releases it on completion, cancellation or failure. Free project workers receive one completion checkpoint after a plain-text ending and must continue with tools or provide an explicit JSON final result. An ignored checkpoint or explicit blocked result reports incomplete; explicit free-worker completion is now reviewed against recorded tool evidence before success is reported.


Worker `edit_file` accepts `path`, non-empty `old_text` and `new_text` (empty is allowed for deletion). It requires one exact match in an existing UTF-8 file and preserves CRLF style. Missing/ambiguous/no-op edits fail without writing. It uses write approval, previews the replacement and rechecks the match after approval. Use it for small changes to large files; reserve `write_file` for new files or deliberate complete rewrites. Free tool-enabled responses marked `finish_reason=length` are discarded before tool execution and the pool tries another model.


Worker function names normalize the known `functions.` prefix and `<|channel|>commentary` / `<|channel|>analysis` suffixes before approvals, restrictions, duplicate detection, execution and model history. Unknown names remain errors. Tool reuse is allowed; repeated identical requests are limited. The incomplete GUI chat attempt is preserved locally on `codex/gui-worker-attempt-20261021` (commit `adbb751`) for review/continuation; it is not merged into main.


Free project workers use a separate per-request response budget: `OVERLORD_FREE_WORK_MAX_TOKENS` defaults to 8192 and is clamped to 64–32768; model-specific caps still apply. Chat keeps `OVERLORD_FREE_MAX_TOKENS` (2048 by default), with no shared-pool mutation. `search_file` now accepts a file, directory or omitted root path and an optional filename `pattern`. It reports matching paths/line numbers, scanned/skipped files and truncation; directory scans reuse discovery exclusions and cap candidate count, file bytes, aggregate searchable bytes and returned matches. Narrow path/pattern if scope is incomplete.


Completion checkpoints reset after a successful worker tool action; they limit consecutive unconfirmed endings rather than the total number of planning messages across productive tool work. Failed tools do not reset them. Empty-response recovery likewise counts consecutive empty responses. The owner live-verified Telegram typing visibility on 1.0.36. Latest partial GUI progress is saved locally as `4bbdaf0` on `codex/gui-worker-attempt-20261021`; continuation still needs to finish console methods and validation.


If present and allowed by worker file restrictions, project `HANDOFF.md` is preloaded alongside explicit file hints, with the existing 4,000-character/file and eight-file bounds. Prior notes are labelled as possibly stale context; current task and source must be reconciled and side effects must not be replayed automatically. The saved GUI branch includes a targeted continuation handoff rather than requiring a fresh repository survey.


Free coding workers submit explicit final claims to a separate LLM completion review using the original task, proposed report and bounded, redacted evidence ledgers (20 action entries plus 20 command entries, 5,000 characters each; up to 16,000 action characters and 24,000 command characters supplied). The reviewer checks requested functionality, successful validation, local commit and requested publication evidence; it does not run tools or interpret intent with keyword rules. Rejections return missing work to the active worker. Repeated rejected finals without successful tool progress, invalid decisions or unavailable review report incomplete. Blocked and answer-only results skip review. This is a model evidence check, not independent execution or proof of correctness. Missing search queries now return the required argument shape and explain that pattern filters filenames.


Free project workers receive a progress checkpoint after 12 steps without a successful write_file/edit_file action. The prompt asks the model to reconcile the original task, implement known changes, investigate specific blockers or synthesize read-only findings; it does not force edits or classify natural-language intent with patterns. Commands retain their own evidence ledger so later reads cannot evict validation/commit results. Step numbers let the completion reviewer compare validation against final edits. Failed commands include the actual shell, selected project interpreter and recovery guidance; Python is already first on PATH.

Before each free worker request, history is capped at 48,000 serialized characters by keeping the original task/instructions, bounded recorded action context and complete recent assistant/tool exchanges. A parallel tool batch is retained or removed as a unit. This is mechanical trimming, not a generated semantic summary or a provider-specific token guarantee. Earlier source contents may need targeted rereading. A task/instruction pair too large for the budget fails explicitly. Free pool exhaustion reports incomplete with available diagnostics rather than crashing or claiming completion. Worker instructions require explicit staging paths and preservation of pre-existing edits/untracked files.

Canonical wheel checks clear only the generated build/lib staging directory after verifying its resolved workspace path. This prevents stale modules from another branch being included in local verification wheels; source files and output artifacts are preserved.


Free workers now retain initial bounded file hints, including HANDOFF.md, through context trimming. Read/list/search duplicate counters refresh when context is trimmed, allowing evicted source results to be reacquired; identical commands and writes remain protected. Actual successful file changes refresh duplicate counters so validation can be repeated after repairs. Identical write_file content returns changed=false without rewriting the file and does not refresh the guard.

Worker update_plan accepts 1-24 steps with step text (up to 200 characters), status pending/in_progress/completed and optional explanation (up to 4,000 characters). It records model-maintained task state in memory for the current run, with no file writes or approval prompt. The latest plan is carried into trimmed context as an assessment, not verified completion. Initial context and latest plan remain under the same serialized input bound.


Free project work now starts with a bounded planning phase exposing only update_plan. Up to three replies are validated before any project action; malformed or unrelated tool calls are never executed during planning. Valid formal or JSON plans seed the existing per-run memory. Planning failure or pool exhaustion reports incomplete. Answer-only work bypasses this phase; configured action-step limits still apply to subsequent project actions.

read_file defaults to a 6,000-character page from the beginning, rather than a 24,000-character tail. Explicit max_chars may still request up to 24,000 characters. Responses include total_lines, next_line and next_column; continue with start_line/start_column to avoid overlap or lost text, including long single lines. Failed command tools distinguish the required code (run_python) and command (run_command) parameters.

Free-model HTTP attempts log model ID, tool availability, input character count, HTTP outcome and elapsed time. Request bodies, keys and provider endpoints are not included in this timing telemetry.


Model-facing worker tool calls reject unknown top-level parameter names and incorrect declared parameter types before approval or execution. Errors return accepted parameter names/types and required fields, without echoing argument values. All advertised tool parameter objects disallow extra properties; the existing cmd alias remains accepted by the run_command runtime. Tool implementations retain their existing path, range and value checks. Malformed formal argument JSON or non-object JSON gets a recoverable argument error instead of crashing the worker. Startup-plan replies use the same boundary. Rejected parameter names/types are logged without their values.


Confirmed file mutations retain their own bounded 20-entry metadata ledger across worker context trimming, independent of read/search history. Progress checkpoints and final review use it to reconcile actual edits with potentially stale plans. Release builds validate their requested version against pyproject.toml and modules/version.py FALLBACK_VERSION before staging/signing; use python tools/check_release_version.py <version-or-tag> locally.

- Worker formal call wrappers are validated as a whole before execution/history: malformed batches return explicit retry guidance, and valid siblings in an invalid batch do not execute. No tool is guessed from arguments.

- After 12 steps without a confirmed file edit, free workers enter a bounded plan-only progress phase. A nonempty model-authored explanation records findings and the next action; the refreshed plan survives context trimming. Three invalid replies or an unavailable pool leave the task incomplete and preserve existing files. Read-only tasks need no artificial writes.

- Completion challenges survive reads, searches, listings, plan updates and unchanged writes. Confirmed edits or successful commands reset them; valid final reports still receive review, including read-only work. Unresolved feedback is pinned across context trimming and progress planning.

- Plan repair retries retain the latest structured correction after trimming, alongside a valid argument example. Nested validation names constraints without submitted values; bounded rejection diagnostics and the final exhausted-retry report identify the specific failure.
