import pytest
from triage_agent.agent import DemoTriageAgent
from triage_agent.models import AgentProposal, Message
from triage_agent.policy import finalize
from triage_agent.tools import ToolRegistry


def mock_proposal(**overrides):
    data = dict(urgency="low", product="App", issue_types=["question"], sentiment="neutral",
        action="auto_respond", assigned_team=None, summary="Customer question", reasons=["Customer asked"],
        kb_article_ids=[], draft_response="Here's the answer.", uncertainties=[])
    data.update(overrides)
    return AgentProposal(**data)


@pytest.mark.parametrize("ticket_id,urgency,action", [
    ("TICKET-001", "high", "escalate_to_human"),
    ("TICKET-002", "critical", "escalate_to_human"),
    ("TICKET-003", "medium", "route_to_specialist"),
])
def test_original_scenarios_demo(tickets, ticket_id, urgency, action):
    result = DemoTriageAgent().run(tickets[ticket_id])
    assert result.urgency == urgency
    assert result.action == action
    assert result.mode == "demo_rules"
    assert {"get_customer_history", "search_knowledge_base"}.issubset(result.tools_used)
    assert all(t.ok for t in result.tool_trace)


def test_billing_unsafe_auto_response_overridden(tickets):
    t = tickets["TICKET-001"]
    tools = ToolRegistry(t)
    result = finalize(t, mock_proposal(draft_response="Your refund has been processed."), tools, "demo_rules")
    assert result.urgency == "high"
    assert result.action == "escalate_to_human"
    assert "refund has been processed" not in result.draft_response
    assert result.assigned_team == "Billing Support"


def test_enterprise_error500_escalates_even_when_green_status(tickets):
    t = tickets["TICKET-002"]
    tools = ToolRegistry(t)
    tools.call("check_system_status", {"region": "Asia"})
    result = finalize(t, mock_proposal(urgency="low"), tools, "demo_rules")
    assert result.urgency == "critical"
    assert result.action == "escalate_to_human"
    assert "region Asia" in result.draft_response


def test_dark_bug_needs_specialist(tickets):
    t = tickets["TICKET-003"]
    result = finalize(t, mock_proposal(urgency="low"), ToolRegistry(t), "demo_rules")
    assert result.urgency == "medium"
    assert result.action == "route_to_specialist"
    assert "isn't confirmed" in result.draft_response


def test_unverified_kb_citation_discarded_and_no_auto_response(tickets):
    t = tickets["TICKET-003"].model_copy(deep=True)
    t.messages = [Message(when="now", text="Hello, how do I get started?")]
    tools = ToolRegistry(t)
    result = finalize(t, mock_proposal(kb_article_ids=["FAKE-KB-999"]), tools, "demo_rules")
    assert result.urgency == "low"
    assert result.kb_article_ids == []
    assert result.action == "route_to_specialist"
    assert "unverified_kb_article_ids_removed" in result.policy_overrides


def test_valid_low_risk_can_auto_respond(tickets):
    t = tickets["TICKET-003"].model_copy(deep=True)
    t.messages = [Message(when="now", text="Hello, how do I get started?")]
    tools = ToolRegistry(t)
    tools.call("search_knowledge_base", {"query": "hello getting started guide"})
    result = finalize(t, mock_proposal(kb_article_ids=["KB-004"]), tools, "demo_rules")
    assert result.urgency == "low"
    assert result.action == "auto_respond"


def test_failed_tool_disables_auto_response(tickets):
    t = tickets["TICKET-003"].model_copy(deep=True)
    t.messages = [Message(when="now", text="Hello, how do I get started?")]
    tools = ToolRegistry(t)
    tools.call("search_knowledge_base", {"query": "hello guide"})
    tools.call("check_billing_status", {"customer_id": "wrong-customer"})
    result = finalize(t, mock_proposal(kb_article_ids=["KB-004"]), tools, "demo_rules")
    assert result.action == "route_to_specialist"
    assert "tool_failure_prevents_auto_response" in result.policy_overrides
