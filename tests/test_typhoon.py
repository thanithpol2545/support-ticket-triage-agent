"""Offline tests for provider interoperability; does not claim real Typhoon calls."""
import json
from types import SimpleNamespace

import pytest

from triage_agent.agent import AgentExecutionError
from triage_agent.typhoon import TyphoonTriageAgent, _chat_tool_schemas


def response(content=None, name=None, arguments=None, id="tc1", finish_reason="stop"):
    calls = [] if name is None else [SimpleNamespace(
        id=id, type="function", function=SimpleNamespace(name=name, arguments=json.dumps(arguments or {})))]
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=calls), finish_reason=finish_reason)])


class FakeCompletions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


class FakeClient:
    def __init__(self, replies):
        self.chat = SimpleNamespace(completions=FakeCompletions(replies))


def proposal_json(**overrides):
    data = dict(urgency="low", product="Pro", issue_types=["billing"], sentiment="angry",
                action="auto_respond", assigned_team=None, summary="Customer reports repeated charges",
                reasons=["Financial risk"], kb_article_ids=["KB-001"],
                draft_response="Refund complete!", uncertainties=[])
    return json.dumps(data | overrides)


def test_typhoon_chat_completion_tool_loop_injected_client(tickets):
    t = tickets["TICKET-001"]
    fake = FakeClient([
        response(name="get_customer_history", arguments={"customer_id":t.customer.customer_id}, id="tool1"),
        response(name="search_knowledge_base", arguments={"query":"payment charge upgrade"}, id="tool2"),
        response(name="check_billing_status", arguments={"customer_id":t.customer.customer_id}, id="tool3"),
        response(content=proposal_json()),
    ])
    result = TyphoonTriageAgent(client=fake).run(t)
    assert result.mode == "live_typhoon"  # simulated client, NOT a live provider test
    assert result.urgency == "high"
    assert result.action == "escalate_to_human"
    assert result.tools_used == ["get_customer_history", "search_knowledge_base", "check_billing_status"]
    requests = fake.chat.completions.requests
    assert len(requests) == 4
    assert requests[0]["tool_choice"]["function"]["name"] == "get_customer_history"
    assert requests[1]["tool_choice"]["function"]["name"] == "search_knowledge_base"
    assert requests[2]["tool_choice"] == "auto"
    assert any(msg["role"] == "tool" and msg["tool_call_id"] == "tool1" for msg in requests[1]["messages"])
    assert all(item["type"] == "function" and "function" in item for item in _chat_tool_schemas())


def test_typhoon_required_tool_missing_fails_closed(tickets):
    client = FakeClient([response(content=proposal_json())])
    with pytest.raises(AgentExecutionError, match="Required tool not called"):
        TyphoonTriageAgent(client=client).run(tickets["TICKET-001"])


def test_typhoon_invalid_final_json_fails_closed(tickets):
    t = tickets["TICKET-001"]
    fake = FakeClient([
        response(name="get_customer_history", arguments={"customer_id":t.customer.customer_id}),
        response(name="search_knowledge_base", arguments={"query":"payment"}),
        response(content="```not json```"),
    ])
    with pytest.raises(AgentExecutionError, match="schema validation"):
        TyphoonTriageAgent(client=fake).run(t)


def test_typhoon_truncated_response_fails_closed(tickets):
    t = tickets["TICKET-001"]
    fake = FakeClient([
        response(name="get_customer_history", arguments={"customer_id":t.customer.customer_id}),
        response(name="search_knowledge_base", arguments={"query":"payment"}),
        response(content=proposal_json(), finish_reason="length"),
    ])
    with pytest.raises(AgentExecutionError, match="truncated"):
        TyphoonTriageAgent(client=fake).run(t)


def test_typhoon_no_key_error_does_not_reveal_secrets(monkeypatch):
    monkeypatch.delenv("TYPHOON_API_KEY", raising=False)
    with pytest.raises(AgentExecutionError, match="TYPHOON_API_KEY"):
        TyphoonTriageAgent()
