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
