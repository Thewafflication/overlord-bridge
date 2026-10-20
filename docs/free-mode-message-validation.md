# Free-mode conversation validation

Validated October 20, 2026 through the owner's live Telegram Overlord chat.
The installed bridge was updated and restarted before the following tests.
No project commands or worker dispatches were requested in these tests.

## Previous behavior

Discussion questions produced lengthy explanations, repeated earlier advice and
unsolicited worker offers. One answer denied that a worker report existed because
the report was absent from the model's history, although it was visible in Telegram.
Opening style instructions alone did not consistently fix the verbosity.

## Live regression results

Prompt: "What do we actually know about the build problem so far? Just discussing;
do not run anything."

Reply:

> So far, we only have a reported TinyCC/WCRT compile error in `print_w32.c`:
> an “incompatible types for redefinition of `_get_osfhandle`” conflict. We have
> not identified either declaration or their origins, applied or tested a fix,
> rebuilt successfully, or confirmed any package/release; the cause and proposed
> preset workaround remain unverified.

Result: focused summary; uncertainty retained; no tool offer, provider diagnostics
or automatic token footer.

Prompt: "Why not just change the preset and see whether it builds?"

Reply:

> Because it tests the symptom, not the cause: a successful build would only show
> that the preset’s include ordering hides the `_get_osfhandle` conflict, not that
> the declarations are compatible. It could also alter include resolution globally
> and break other toolchains, leaving an unverified workaround rather than a
> justified fix.

Result: concise, no tutorial or worker offer. Its assertion that a successful
build would *only* hide the conflict is too strong; a follow-up correction tests
whether the model distinguishes this hypothesis from established facts.

Prompt: "That does not prove the preset is wrong, though. What is known versus
still a hypothesis?"

Reply:

> **Known:** TinyCC/WCRT reportedly fails in `print_w32.c` because `_get_osfhandle`
> is redefined with incompatible types. **Still unknown:** which declarations
> conflict, where they originate, what the proposed preset changes, and whether
> it yields a successful full build. **Hypothesis:** the preset may resolve the
> conflict by changing include or definition visibility, or merely mask an
> underlying header incompatibility—it is neither proven wrong nor validated
> as a fix.

Result: accepted the correction, distinguished reported evidence from hypotheses,
and stopped without a worker offer.

These replies are conversation-quality evidence, not verification of the build
diagnosis or proposed fix. They do not prove all free models follow the contract.

## Automated checks

`python tools/check.py all`: lint and wheel build passed; 1,124 tests passed,
one skipped. Targeted tests cover tool-free reply editing, combined usage,
preservation of requested long artifacts, and delivery of the original answer
when editing is unavailable. Worker report persistence and quiet token accounting
are also covered.

## Operational tradeoff

Replies over 80 words incur at most one additional free-model call, bounded by
30 seconds. Editing shares provider budgets and may be skipped when unavailable.
The model decides how much detail the current request requires; the bridge does
not truncate the answer or classify the owner's intent with keyword rules.
