# Overlord roadmap

Success means useful project work with relevant validation, a local commit and a verified upstream push when requested. More model names or successful dispatches alone do not establish worker capacity.

## Provider capacity

- [ ] Qualify Groq on the owner's Free-plan key with a real reproduce/fix/test/commit/push run. The adapter, key settings and provider-wide request/token backoff are implemented; live entitlement and throughput require the owner's key. Account quotas remain authoritative.
- [ ] Add Cloudflare Workers AI as an independent fallback provider. Verify currently free-access models, tool-call compatibility and per-account permissions; implement neuron-aware budgets and prevent automatic paid-plan fallback. Qualify with completed project work. Reference: https://developers.cloudflare.com/workers-ai/platform/pricing/
- [ ] Evaluate and add Mistral where the owner's account has usable free API entitlement. Verify current account/model availability instead of assuming advertised Free mode grants inference. Implement shared request/token/monthly quotas, explicit consent and no automatic paid upgrade. Qualify with completed project work. Reference: https://docs.mistral.ai/admin/billing-usage/usage-limits

## Continuous work

- [x] Keep active worker context while temporary provider capacity recovers; wait cooperatively and retain local stop control. Foreground chat remains bounded. Permanent request/key/configuration errors still fail explicitly.
- [ ] Persist a resumable worker checkpoint across bridge shutdown/restart, so a long capacity wait survives maintenance without replaying completed commands or starting project discovery again.
- [ ] Measure real provider token allowances and completed validated/pushed milestones. Tune request context/output budgets and fair project scheduling from those results. Free quotas can delay work; no finite pool guarantees uninterrupted inference.
