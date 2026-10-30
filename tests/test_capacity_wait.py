"""Capacity recovery retains the outstanding request; cancellation remains prompt."""
import asyncio
from types import SimpleNamespace

import pytest

from modules.free_brain import FreeUnavailable, ModelSpec
from modules.free_work import FreeWork


def test_real_groq_pool_resumes_after_quota_reset_without_replaying_request(tmp_path, monkeypatch):
    from modules import free_brain
    clock = [1800000000.0]
    calls, sleeps, sent = [], [], []
    async def post(url, payload, key, timeout):
        calls.append(payload['messages'])
        if len(calls) == 1:
            return 429, {'retry-after': '120'}, {}
        return 200, {}, {'choices': [{'message': {'content': 'capacity restored'}}]}
    async def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(free_brain, '_post', post)
    monkeypatch.setattr('modules.free_work.asyncio.sleep', sleep)
    brain = free_brain.FreeBrain(session_file=tmp_path / 'session',
        models=[ModelSpec('groq', 'openai/gpt-oss-120b')], keys={'groq': 'synthetic'}, groq_enabled=True,
        limiter=free_brain.UsageLimiter(None, {'groq': (10, 250)}, lambda: clock[0]))
    async def pool(): return brain
    work = FreeWork(send=lambda _, text: sent.append(text), roots=lambda: [], workers=SimpleNamespace(owner=42),
                    gate=None, pool=pool, patience=0)
    messages = [{'role': 'user', 'content': 'Continue existing validated edits; commit and push.'}]
    result = asyncio.run(work.complete(messages, None))
    assert result['content'] == 'capacity restored'
    assert len(calls) == 2 and all(m is messages for m in calls)
    assert sleeps == [60, 60] and len(sent) == 2


def test_wait_recovers_with_same_context_and_refreshes_provider_settings(monkeypatch):
    messages = [{'role': 'user', 'content': 'Keep existing edits, validate and commit.'}]
    tools = [{'type': 'function', 'function': {'name': 'finish_task'}}]
    seen, sleeps, sent = [], [], []
    async def exhausted(m, t, **kwargs):
        seen.append((m, t))
        raise FreeUnavailable(['quota exhausted'], 120, retryable=True)
    async def available(m, t, **kwargs):
        seen.append((m, t))
        return {'content': 'resumed'}, ModelSpec('groq', 'openai/gpt-oss-120b'), []
    pools = [SimpleNamespace(complete=exhausted), SimpleNamespace(complete=available)]
    async def pool(): return pools.pop(0)
    async def sleep(seconds): sleeps.append(seconds)
    monkeypatch.setattr('modules.free_work.asyncio.sleep', sleep)
    work = FreeWork(send=lambda _, text: sent.append(text), roots=lambda: [],
                    workers=SimpleNamespace(owner=42), gate=None, pool=pool, patience=0)
    result = asyncio.run(work.complete(messages, tools))
    assert result['_free_model'] == 'groq:openai/gpt-oss-120b'
    assert sleeps == [60] and len(sent) == 2
    assert all(m is messages and t is tools for m, t in seen)


def test_capacity_wait_is_cancellable():
    async def scenario():
        entered = asyncio.Event()
        async def complete(*args, **kwargs):
            entered.set()
            raise FreeUnavailable(['quota exhausted'], 60, retryable=True)
        async def pool(): return SimpleNamespace(complete=complete)
        work = FreeWork(send=lambda *a: None, roots=lambda: [], workers=SimpleNamespace(owner=42),
                        gate=None, pool=pool, patience=0)
        task = asyncio.create_task(work.complete([], None))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())


@pytest.mark.parametrize('retryable,enabled', [(False, True), (True, False)])
def test_configuration_failure_or_opt_out_does_not_wait(retryable, enabled):
    async def complete(*args, **kwargs):
        raise FreeUnavailable(['unavailable'], 60, retryable=retryable)
    async def pool(): return SimpleNamespace(complete=complete)
    work = FreeWork(send=lambda *a: None, roots=lambda: [], workers=SimpleNamespace(owner=42),
                    gate=None, pool=pool, patience=0, wait_for_capacity=enabled)
    with pytest.raises(FreeUnavailable): asyncio.run(work.complete([], None))
