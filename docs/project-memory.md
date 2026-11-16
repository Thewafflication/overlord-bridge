# Persistent worker project memory

Local-agent, NVIDIA and free-pool coding workers retain observations outside
their active model context. The harness automatically archives allowed source
reads, searches, listings, command results, file-change metadata and accepted
model plans. The model decides what to retrieve using two read-only tools:

- `memory_search(query, limit)`: rank literal query terms across stored records;
  an empty query lists recent entries. Returns at most eight metadata previews.
- `memory_read(id, offset, max_chars)`: page a record, default 3,000 characters,
  at most 6,000. Continue with `next_offset` until null. Pages contain serialized
  historical tool results or model plans and may begin/end inside that text.

There are no embeddings, external indexing service or extra model calls. A small
startup index supplies recent IDs and the latest model-assessed next action.
Workers retrieve details during execution or the existing read-only discovery
allowance. Startup planning remains plan-only. Retrieved pages enter the next
model request as tool data; they do not enlarge a provider's context window or
stream into an already generating response. Compaction preserves IDs, freshness
and exact paging offsets.

## Evidence and freshness

Records have an ID, kind, first/last-seen time, and originating run/action when
available. Bodies include the Git revision observed at run start, if available;
this does not claim HEAD is unchanged after later commits. Source records carry
a SHA256 of the full decoded source observed by read_file. Retrieval compares
current source and reports unchanged, changed, unavailable or unchecked. The
latter covers missing hashes and files above the two-megabyte freshness ceiling.
Existing path restrictions are rechecked before exposing source records or
opening their current files.

Commands are historical observations; plans and decisions are model assessments.
Neither an old successful command nor an unchanged hash proves current acceptance.
Workers must reconcile current instructions, read current source before editing
changed/unchecked files, and validate actual changes. Retrieval grants no
permission to replay side effects. It does not reset completion challenges,
count as a new observation, or bypass repeated-discovery limits.

## Storage and failures

Memory lives under worker_reports/memory/<project-hash>.sqlite3, outside the
worker checkout. Scope is the canonical absolute project path, shared between
workers on that project. Different worktrees/paths have separate stores. Python's
SQLite needs no new dependency. Existing package persistence copies the report
tree, retaining memory through upgrades. /new does not delete it. Old reports
are not retroactively imported; moving a checkout starts another scope.

Each project retains at most 512 distinct records, each with a 32,000-character
body plus an explicit truncation marker. Long command streams retain at most
6,000 characters from each tail; original tool results are unchanged. Identical
records refresh last-seen time instead of consuming another entry. At capacity,
oldest records are evicted and search/index responses disclose the count.
SQLite has an approximately 96 MiB page ceiling per project. This is bounded
retention, not an unlimited archive or encrypted storage.

Known environment secrets are redacted before persistence. Linked storage and
SQLite sidecars are rejected. Database errors produce an explicit retrieval
error or save warning while preserving current tool results. Without report
storage, memory is unavailable. Cancellation waits for owned local memory I/O
before acknowledging cleanup so an upgrade cannot race an unfinished write.

## Measured checks

A controlled integration reads source in one run, starts a fresh worker manager
without prior dialogue, retrieves one page of at most 1,000 characters, edits
the actual file, runs an assertion and makes a real local Git commit. The second
worker makes zero read_file calls. This verifies mechanics with scripted model
responses; it is not a model-quality benchmark or a live project delivery.

Reports expose project_memory.searches, pages, retrieved_chars and archive_links.
Archive links include duplicates, not unique findings. Assess these with repeat
reads, worker time, tokens and acceptance-verified completions under equal budgets.
The existing small-provider-context regression still reaches validation, commit
and push. Groq character estimates below protected context now try a smaller
valid request without discarding owner requirements; provider retries remain
bounded as before.
