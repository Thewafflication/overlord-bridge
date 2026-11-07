import pytest
from modules import worker_readiness as readiness


def test_ready_requires_outcome_and_acceptance_but_blockers_can_lack_them():
    value = dict(state='ready', requirement='', deliverable='', acceptance='', evidence='Known state', reason='Missing work')
    assert len(readiness.issues(value)) == 3
    value['state'] = 'needs_planning'
    assert readiness.issues(value) == []
    assert readiness.issues(None, required=True)
    assert readiness.issues(None) == []


@pytest.mark.parametrize('value', [[], {'state': []}, dict(state=[], requirement='', deliverable='',
    acceptance='', evidence='Known state', reason='Unknown'), dict(state='ready', requirement=4,
    deliverable='Change', acceptance='Check', evidence='Known', reason='x' * 1001)])
def test_malformed_assessments_are_rejected_without_crashing(value):
    assert readiness.issues(value)
