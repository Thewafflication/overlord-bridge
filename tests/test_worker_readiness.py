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


@pytest.mark.parametrize('action', [None, 7, 'x' * 1001, 'Run the failing test'])
def test_review_requires_explicit_absence_of_authorized_next_action(action):
    value = dict(state='needs_planning', requirement='Implement queue ordering',
                 deliverable='Ordered queue', acceptance='Run queue tests', evidence='Pending requirement',
                 reason='Need policy choice', owner_question='Which tie-breaking policy?')
    if action is not None:
        value['next_action'] = action
    assert readiness.review_issues(value)


def test_review_can_honor_real_owner_decision_and_admit_technical_action():
    value = dict(state='needs_planning', requirement='Implement queue ordering',
                 deliverable='Ordered queue', acceptance='Run queue tests', evidence='Pending requirement',
                 reason='Need policy choice', owner_question='Which tie-breaking policy?', next_action='')
    assert readiness.review_issues(value) == []
    value.update(state='ready', next_action='Run the existing queue baseline')
    assert readiness.review_issues(value) == []
