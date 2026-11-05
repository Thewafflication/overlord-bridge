"""Routing changes preference, never admission, budgets or provider boundaries."""
from modules.free_brain import ModelSpec
from modules.free_routing import WorkerRouting, route_request
from modules.request_budget import BudgetedMessages
from modules.workers import _worker_plan_result


def test_routine_complex_and_independent_review_order():
    small = ModelSpec('nvidia', 'openai/gpt-oss-20b')
    strong = ModelSpec('nvidia', 'openai/gpt-oss-120b')
    other = ModelSpec('nvidia', 'nvidia/nemotron-3-super-120b-a12b')
    unknown = ModelSpec('openrouter', 'new/vendor:free')
    pool = [small, strong, unknown, other]
    assert sorted(pool, key=WorkerRouting('routine').rank)[0] == small
    assert sorted(pool, key=WorkerRouting('complex').rank)[0] == strong
    assert sorted(pool, key=WorkerRouting('routine', escalated=True).rank)[0] == strong
    assert sorted(pool, key=WorkerRouting('routine', 'plan').rank)[0] == strong
    review = WorkerRouting('routine', 'review', previous_model=strong.key)
    assert sorted(pool, key=review.rank)[0] == other
    assert sorted([small], key=review.rank) == [small]


def test_routing_is_request_local_and_preserves_fitting():
    request = BudgetedMessages([{'role':'user','content':'x'}], lambda limit: [])
    routed = route_request(request, WorkerRouting('complex'))
    assert routed is request and routed.fit(2000) == list(request)
    assert not hasattr(route_request([], WorkerRouting('routine')).worker_routing, 'provider')
    assert not hasattr([], 'worker_routing')


def test_difficulty_is_validated_and_retained_without_requiring_legacy_plans():
    plan = {'plan':[{'step':'Fix and validate','status':'pending'}]}
    assert _worker_plan_result(plan)['ok']
    assessment = {'level':'complex','reason':'ABI and toolchain evidence conflict'}
    assert _worker_plan_result(dict(plan, difficulty=assessment))['plan']['difficulty'] == assessment
    for invalid in ({'level': [], 'reason':'x'}, {'level':'complex','reason':''}, 'complex'):
        assert not _worker_plan_result(dict(plan, difficulty=invalid))['ok']
