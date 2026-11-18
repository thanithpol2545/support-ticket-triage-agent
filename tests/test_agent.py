import json
from types import SimpleNamespace
import pytest
from triage_agent.agent import GPTTriageAgent, AgentExecutionError


def call(name, args, call_id):
    return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=call_id)


def response(items=None, text=""):
    return SimpleNamespace(output=items or [], output_text=text)


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


def test_live_agent_real_tool_loop_with_fake_sdk(tickets):
    t = tickets["TICKET-001"]
    client = FakeClient([
        response([call("get_customer_history", {"customer_id": t.customer.customer_id}, "1")]),
        response([call("search_knowledge_base", {"query": "duplicate payment charges upgrade"}, "2")]),
        response([call("check_billing_status", {"customer_id": t.customer.customer_id}, "3")]),
        response(text=model_json()),
    ])
    result = GPTTriageAgent(client=client).run(t)
    assert result.mode == "live_gpt"
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
        response(text='{"urgency":"unacceptable"}'),
    ])
    with pytest.raises(AgentExecutionError, match="Invalid model output"):
        GPTTriageAgent(client=client).run(t)


def test_wrong_customer_tool_call_fails_closed(tickets):
    client = FakeClient([response([call("get_customer_history", {"customer_id": "another-id"}, "1")])])
    with pytest.raises(AgentExecutionError, match="Required tool failed"):
        GPTTriageAgent(client=client).run(tickets["TICKET-001"])


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
