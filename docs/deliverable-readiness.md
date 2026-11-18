# Deliverable readiness

Free workers previously needed a well-shaped plan, but a plan to reread documents
or refresh old commit references satisfied that check. Scheduled runs could spend
dozens of actions repeating discovery without identifying useful unfinished work.

Before actions, and at later planning checkpoints, `update_plan` now includes a
structured `readiness` assessment. Its fields are `state`, `requirement`,
`deliverable`, `acceptance`, `evidence` and `reason`. Each text field is bounded
to 1,000 characters. Ready assessments require nonempty fields and, at initial
admission or discovery reassessment, at least one unfinished plan step. Later
progress plans may record completed steps before normal completion review.
The model interprets the request and evidence; no task-word
classifier decides whether documentation or code is valuable.

| State | Worker behavior |
| --- | --- |
| `ready` | Run the existing tool workflow, permission and acceptance checks. |
| `discovery` | Up to six file read/search/list or plan actions; commands, writes and completion are denied. Reassess once when exhausted. |
| `needs_planning` | Yield incomplete with the missing product decision. |
| `blocked` | Yield incomplete with the concrete prerequisite. |
| `already_complete` | Yield incomplete for this dispatch, explaining prior completion and absence of further authorized work. |

Discovery cannot be renewed by another plan, progress checkpoint, command attempt
or context trim. A discovery reassessment must establish ready work or yield.
Ordinary `update_plan` actions retain the admitted state rather than replacing
it. Malformed/missing assessments receive the existing three bounded planning
retries, with no project actions during that phase. A formal success response
while still discovering cannot reach completion review.

Terminal reports include `work_readiness`; incomplete continuations retain the
plan and assessment for the next run. Schedules remain installed and active;
the gate neither edits project records nor manufactures a task queue. It does
not automatically pause a blocked project or prevent the next scheduled
assessment. Owner-defined acceptance queues remain authoritative.
The model's acceptance text is recorded as a plan; this gate does not execute
that text or treat it as a passing test result.

Before yielding `needs_planning`, `blocked` or `already_complete`, the worker
now obtains one additional readiness assessment. This addresses observed stops
whose reason was simply that identified actions had not been executed yet.
The review reconciles the owner request, acceptance queue and current evidence.
Unread source and a known failing build can be the subject of a ready bounded
investigation; `needs_planning` is reserved for an actual missing owner decision
or requirement. Confirmed early stops remain incomplete outcomes.

Review uses the existing free-pool review routing, preferring a different model
family when available; it does not add paid capacity or grant permissions.
Planning and review each have at most three schema attempts, six total, with no
project actions during either stage. Reviewer outage or invalid responses do
not admit work. A review cannot renew exhausted discovery or override owner
acceptance failures. Reports retain the proposal, decision and model in
`readiness_review`; a second assessment can still be wrong.

The assessment can still be wrong: invented evidence, weak acceptance criteria
or an unjustified ready decision require independent review. This gate limits
work admitted as unknown; it does not guarantee meaningful commits, require
commits for no-op verification, or replace build/runtime acceptance checks.

A reviewer confirming needs_planning must provide a specific owner_question.
Missing questions consume bounded correction attempts rather than confirming an
unsupported stop; confirmed questions appear in the report. This requirement
checks the review contract, not the semantic quality of the question.

An attempted return to discovery after its allowance was used is also a proposed
early stop and receives review. The reviewer is told the allowance was used;
another discovery decision consumes the existing three correction attempts.
The harness never converts that decision into needs_planning itself. Review can
admit bounded technical work or confirm a concrete stop with the usual contract.

Reviewers confirming needs_planning must also supply next_action: useful
authorized technical work possible before an owner answer, or an empty string
only when none exists. A nonempty action contradicts needs_planning and receives
bounded correction asking for ready plus that action. Missing or malformed
assessments also consume the existing three review attempts. Exhaustion preserves
the proposal and yields incomplete without project actions. The model interprets
actionability; Python checks the explicit contract, never question keywords.
An incorrect empty action can still produce an unjustified stop. This does not
guarantee model quality or replace independent acceptance.
