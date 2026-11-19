import json
import traceback
from types import SimpleNamespace

import pytest
from openai import DefaultHttpxClient, OpenAI
from triage_agent.agent import GPTTriageAgent, AgentExecutionError

# SDK 2 uses httpx. Later SDKs may provide the compatible httpx2 transport.
try:
    import httpx2
except ImportError:
    httpx2 = None

if httpx2 is not None and issubclass(DefaultHttpxClient, httpx2.Client):
    http = httpx2
else:
    import httpx as http


def call(name, args, call_id):
    return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=call_id)


def response(items=None, text="", status="completed"):
    return SimpleNamespace(output=items or [], output_text=text, status=status)


class FakeResponses:
    def __init__(self, responses):
        self.items = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.items.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.responses = FakeResponses(responses)


def model_json(**overrides):
    data = dict(urgency="low", product="Pro", issue_types=["billing"], sentiment="angry",
        action="auto_respond", assigned_team=None, summary="Repeated charges and failed upgrade",
        reasons=["User reports three charges"], kb_article_ids=["KB-001"],
        draft_response="Your refund has been processed.", uncertainties=[])
    data.update(overrides)
    return json.dumps(data)


def test_agent_tool_loop_with_fake_sdk(tickets):
    t = tickets["TICKET-001"]
    client = FakeClient([
        response([call("get_customer_history", {"customer_id": t.customer.customer_id}, "1")]),
        response([call("search_knowledge_base", {"query": "duplicate payment charges upgrade"}, "2")]),
        response([call("check_billing_status", {"customer_id": t.customer.customer_id}, "3")]),
        response(text=model_json()),
    ])
    result = GPTTriageAgent(client=client).run(t)
    assert result.action == "escalate_to_human"  # policy supersedes unsafe model advice
    assert result.urgency == "high"
    assert result.tools_used == ["get_customer_history", "search_knowledge_base", "check_billing_status"]
    assert len(client.responses.requests) == 4
    assert client.responses.requests[0]["tool_choice"]["name"] == "get_customer_history"
    assert client.responses.requests[1]["tool_choice"]["name"] == "search_knowledge_base"
    assert client.responses.requests[2]["tool_choice"] == "auto"
    assert client.responses.requests[3]["store"] is False
    assert client.responses.requests[3]["text"]["format"]["strict"] is True
    # Tool output is appended back to model input, not merely logged.
    assert any(isinstance(x, dict) and x.get("type") == "function_call_output" for x in client.responses.requests[3]["input"])


def test_forced_tool_missing_fails_closed(tickets):
    client = FakeClient([response(text=model_json())])
    with pytest.raises(AgentExecutionError, match="Required tool not called"):
        GPTTriageAgent(client=client).run(tickets["TICKET-001"])


def test_invalid_gpt_json_fails_closed(tickets):
    t = tickets["TICKET-001"]
    client = FakeClient([
        response([call("get_customer_history", {"customer_id": t.customer.customer_id}, "1")]),
        response([call("search_knowledge_base", {"query": "payment charge"}, "2")]),
        response(text=model_json(urgency='PRIVATE_TEST_MARKER')),
    ])
    with pytest.raises(AgentExecutionError, match="Invalid model output") as exc:
        GPTTriageAgent(client=client).run(t)
    assert 'PRIVATE_TEST_MARKER' not in ''.join(traceback.format_exception(exc.value))


def test_wrong_customer_tool_call_fails_closed(tickets):
    client = FakeClient([response([call("get_customer_history", {"customer_id": "another-id"}, "1")])])
    with pytest.raises(AgentExecutionError, match="Required tool failed"):
        GPTTriageAgent(client=client).run(tickets["TICKET-001"])


@pytest.mark.parametrize('kb_response,error', [
    (response(text=model_json()), 'Required tool not called: search_knowledge_base'),
    (response([call('search_knowledge_base', {'query': ''}, '2')]), 'Required tool failed: search_knowledge_base'),
])
def test_no_final_proposal_without_a_successful_kb_call(tickets, kb_response, error):
    ticket = tickets['TICKET-001']
    client = FakeClient([
        response([call('get_customer_history', {'customer_id': ticket.customer.customer_id}, '1')]),
        kb_response,
    ])
    with pytest.raises(AgentExecutionError, match=error):
        GPTTriageAgent(client=client).run(ticket)
    assert len(client.responses.requests) == 2


def test_api_failure_is_reported_without_unsafe_fallback(tickets):
    client = FakeClient([])
    with pytest.raises(AgentExecutionError, match="OpenAI response failed"):
        GPTTriageAgent(client=client).run(tickets["TICKET-001"])


def test_provider_error_does_not_leak_secret_or_request_content(tickets):
    class FailingAPI:
        def create(self, **kwargs):
            raise RuntimeError('provider metadata token=SENSITIVE-EXAMPLE-CANARY')
    class Client:
        responses = FailingAPI()
    with pytest.raises(AgentExecutionError) as exc:
        GPTTriageAgent(client=Client()).run(tickets['TICKET-001'])
    assert 'SENSITIVE-EXAMPLE-CANARY' not in str(exc.value)
    assert 'RuntimeError' in str(exc.value)


@pytest.mark.parametrize('status', ['incomplete', 'failed'])
def test_unsuccessful_response_cannot_be_used_as_final_proposal(tickets, status):
    t = tickets['TICKET-001']
    client = FakeClient([
        response([call('get_customer_history', {'customer_id': t.customer.customer_id}, '1')]),
        response([call('search_knowledge_base', {'query': 'duplicate payment'}, '2')]),
        response(text=model_json(), status=status),
    ])
    with pytest.raises(AgentExecutionError, match='did not complete'):
        GPTTriageAgent(client=client).run(t)


def test_repeated_tool_calls_stop_at_round_limit(tickets):
    t = tickets['TICKET-001']
    client = FakeClient([
        response([call('get_customer_history', {'customer_id': t.customer.customer_id}, '1')]),
        response([call('search_knowledge_base', {'query': 'duplicate payment'}, '2')]),
        response([call('search_knowledge_base', {'query': 'another lookup'}, '3')]),
    ])
    with pytest.raises(AgentExecutionError, match='Maximum tool rounds'):
        GPTTriageAgent(client=client, max_rounds=3).run(t)
    assert len(client.responses.requests) == 3


def test_responses_sdk_serializes_tools_and_validates_final_answer(tickets):
    t = tickets['TICKET-001']
    requests = []
    replies = iter([
        {'type': 'function_call', 'name': 'get_customer_history', 'call_id': 'call_history',
         'id': 'fc_history', 'arguments': json.dumps({'customer_id': t.customer.customer_id})},
        {'type': 'function_call', 'name': 'search_knowledge_base', 'call_id': 'call_kb',
         'id': 'fc_kb', 'arguments': json.dumps({'query': 'duplicate payment charges upgrade'})},
        {'type': 'message', 'role': 'assistant', 'id': 'msg_final', 'status': 'completed',
         'content': [{'type': 'output_text', 'text': model_json(), 'annotations': []}]},
    ])

    def respond(request):
        assert request.url.path == '/v1/responses'
        requests.append(json.loads(request.content))
        return http.Response(200, json={'status': 'completed', 'output': [next(replies)]})

    with OpenAI(api_key='test-credential', http_client=http.Client(transport=http.MockTransport(respond))) as client:
        result = GPTTriageAgent(client=client).run(t)

    assert result.action == 'escalate_to_human'
    assert result.tools_used == ['get_customer_history', 'search_knowledge_base']
    assert requests[0]['tool_choice']['name'] == 'get_customer_history'
    assert requests[1]['tool_choice']['name'] == 'search_knowledge_base'
    returned = [item for item in requests[2]['input'] if item.get('type') == 'function_call_output']
    assert [item['call_id'] for item in returned] == ['call_history', 'call_kb']
    assert json.loads(returned[1]['output'])['articles'][0]['id'] == 'KB-001'


@pytest.mark.parametrize('failure,error_type', [('timeout', 'APITimeoutError'), ('rate-limit', 'RateLimitError')])
def test_sdk_failures_come_back_as_safe_errors(tickets, failure, error_type):
    def respond(request):
        if failure == 'timeout':
            raise http.ReadTimeout('PRIVATE_TEST_MARKER', request=request)
        return http.Response(429, json={'error': {'message': 'PRIVATE_TEST_MARKER'}})

    transport = http.MockTransport(respond)
    with OpenAI(api_key='test-credential', max_retries=0, http_client=http.Client(transport=transport)) as client:
        with pytest.raises(AgentExecutionError, match=error_type) as exc:
            GPTTriageAgent(client=client).run(tickets['TICKET-001'])
    assert 'PRIVATE_TEST_MARKER' not in ''.join(traceback.format_exception(exc.value))
