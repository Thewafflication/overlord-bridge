import json
import pytest
from modules.request_budget import BudgetedMessages,review_messages,size
from modules.workers import _bounded_worker_messages,_budgeted_planning_request


def context():
    return [{'role':'system','content':'Keep all owner instructions.'},{'role':'user','content':'Repair the requested queue regression.'},
        {'role':'assistant','content':'Older inspected source. '*2500},
        {'role':'assistant','tool_calls':[{'id':'recent','function':{'name':'read_file','arguments':'{}'}}]},
        {'role':'tool','tool_call_id':'recent','content':'Latest failing assertion and source region.'}]


def worker_request(messages=None):
    messages=messages or context()
    return BudgetedMessages(messages,lambda limit:_bounded_worker_messages(messages,['failed regression'],limit=limit,
        prefix_count=2,plan={'explanation':'Queue source inspected; fix then validate.','plan':[{'step':'Repair queue','status':'in_progress'}]},
        mutations=['queue.py changed'],completion_feedback='Preserve failure behavior.'))


def test_worker_fit_preserves_task_and_complete_tool_exchange():
    original=context();request=worker_request(original);fitted=request.fit(12000)
    assert fitted[:2]==original[:2] and size(fitted)<=12000
    assert fitted[-2:]==original[-2:]
    assert 'queue.py changed' in str(fitted) and 'Preserve failure behavior' in str(fitted)
    assert 'Queue source inspected' in str(fitted)
    assert json.loads(json.dumps(request))==original
    assert size(original)>40000


def test_planning_fit_rebuilds_read_only_json_and_keeps_correction():
    original=context();request=[{'role':'system','content':'Only record update_plan.'},
        {'role':'user','content':'Read-only worker context:\n'+json.dumps(original)},
        {'role':'user','content':'Record current findings.'},{'role':'user','content':'Specific schema correction remains required.'}]
    wrapped=_budgeted_planning_request(request,original,['regression failed'],prefix_count=2,plan=None,mutations=['queue.py changed'],completion_feedback='Keep failure case')
    fitted=wrapped.fit(13000);assert size(fitted)<=13000
    assert fitted[0]==request[0] and fitted[2:]==request[2:]
    inner=json.loads(fitted[1]['content'].split('\n',1)[1]);assert inner[:2]==original[:2]
    assert inner[-2:]==original[-2:]


def test_review_fit_keeps_task_report_and_marks_partial_evidence():
    data={'task':'Repair real coverage, do not delete assertions.','proposed_final':'Worker claim needs verification.',
        'tool_evidence':'command evidence '*4000,'independent_git_changes':{'partial':False,'files':[
            {'path':'test_queue.py','untracked':False,'content':'old assertions '*1500,'truncated':False}]}}
    messages=[{'role':'system','content':'Assess actual task and evidence.'},{'role':'user','content':json.dumps(data)}]
    fitted=review_messages(messages).fit(10000);result=json.loads(fitted[1]['content'])
    assert result['task']==data['task'] and result['proposed_final']==data['proposed_final']
    assert result['tool_evidence_truncated'] and result['independent_git_changes']['partial']
    assert result['independent_git_changes']['files'][0]['truncated']
    assert json.loads(messages[1]['content'])==data


def test_fit_refuses_to_discard_protected_instructions():
    request=worker_request([{'role':'system','content':'Protected instruction '*2000},{'role':'user','content':'Actual task'}])
    with pytest.raises(ValueError):request.fit(5000)


@pytest.mark.parametrize('escaped', ['"', '\\'])
def test_planning_fit_refines_last_budget_interval_before_rejecting(escaped):
    # A coarse reduction can jump below the protected floor even though a
    # request between the two attempted budgets fits. Model the large pinned
    # prefix and optional action evidence seen in the live KerTeX checkpoint.
    prefix = [{'role': 'system', 'content': 'I' * 8000},
              {'role': 'user', 'content': 'T' * 7500},
              {'role': 'user', 'content': 'P' * 21000}]
    original = prefix + [{'role': 'assistant', 'content': 'older exchange ' * 1000}]
    plan = {'explanation': escaped * 1200,
            'plan': [{'step': 'Use recorded evidence for the next concrete check', 'status': 'in_progress'}]}
    request = [{'role': 'system', 'content': 'O' * 1075},
               {'role': 'user', 'content': 'Read-only worker context:\n' + json.dumps(original)},
               {'role': 'user', 'content': 'Record findings.'}]
    # Search the narrow boundary independently: establish that protected
    # content fits, then require the public fitter to find it with metadata.
    evidence = ['optional recorded action ' * 400]
    feasible = None
    for budget in range(43000, 36500, -25):
        try:
            bounded = _bounded_worker_messages(original, evidence, limit=budget,
                prefix_count=3, plan=plan, mutations=['source.c changed'], completion_feedback='Keep required validation')
        except ValueError:
            continue
        candidate = [dict(m) for m in request]
        candidate[1]['content'] = 'Read-only worker context:\n' + json.dumps(bounded, ensure_ascii=False)
        if size(candidate) <= 48000:
            feasible = candidate
            break
    assert feasible is not None
    fitted = _budgeted_planning_request(request, original, evidence, prefix_count=3,
        plan=plan, mutations=['source.c changed'], completion_feedback='Keep required validation')
    assert size(fitted) <= 48000
    assert fitted[0] == request[0] and fitted[2:] == request[2:]
    inner = json.loads(fitted[1]['content'].split('\n', 1)[1])
    assert inner[:3] == prefix
    assert json.dumps(plan, ensure_ascii=False) in inner[3]['content']
    assert 'source.c changed' in inner[3]['content'] and 'Keep required validation' in inner[3]['content']


def test_planning_fit_rejects_genuinely_oversized_outer_instructions():
    original = [{'role': 'system', 'content': 'Protected worker task'}]
    request = [{'role': 'system', 'content': 'Protected planning rules' * 3000},
               {'role': 'user', 'content': 'Read-only worker context:\n' + json.dumps(original)}]
    with pytest.raises(ValueError):
        _budgeted_planning_request(request, original, [], prefix_count=1,
            plan=None, mutations=[], completion_feedback='')
