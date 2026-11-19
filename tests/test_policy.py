import pytest
from triage_agent.models import AgentProposal, Message
from triage_agent.policy import finalize
from triage_agent.tools import ToolRegistry


def mock_proposal(**overrides):
    data = dict(urgency="low", product="App", issue_types=["question"], sentiment="neutral",
        action="auto_respond", assigned_team=None, summary="Customer question", reasons=["Customer asked"],
        kb_article_ids=[], draft_response="Here's the answer.", uncertainties=[])
    data.update(overrides)
    return AgentProposal(**data)


def test_billing_unsafe_auto_response_overridden(tickets):
    t = tickets["TICKET-001"]
    tools = ToolRegistry(t)
    result = finalize(t, mock_proposal(draft_response="Your refund has been processed."), tools)
    assert result.urgency == "high"
    assert result.action == "escalate_to_human"
    assert "refund has been processed" not in result.draft_response
    assert result.assigned_team == "Billing Support"


def test_enterprise_error500_escalates_even_when_green_status(tickets):
    t = tickets["TICKET-002"]
    tools = ToolRegistry(t)
    tools.call("check_system_status", {"region": "Asia"})
    result = finalize(t, mock_proposal(urgency="low"), tools)
    assert result.urgency == "critical"
    assert result.action == "escalate_to_human"
    assert "regional scope" in result.draft_response



@pytest.mark.parametrize('message,broad_outage', [
    pytest.param('All users get HTTP 500.', True, id='group-first'),
    pytest.param('HTTP 500 affects all users.', True, id='affects'),
    pytest.param('HTTP 500 is affecting all users.', True, id='is-affecting'),
    pytest.param(
        "I don't think HTTP 500 affects all users. Only I get the error.", False, id='doubt-about-scope',
    ),
    pytest.param(
        'HTTP 500 affects all users? Everyone can log in.', False, id='asks-about-scope',
    ),
    pytest.param(
        'HTTP 500 affects all our users. Can you check?', True, id='affirmed-before-question',
    ),
])
def test_broad_outage_overrides_simulated_low_auto_respond_proposal(tickets, message, broad_outage):
    ticket = tickets['TICKET-002'].model_copy(update={'messages': [Message(when='now', text=message)]})
    tools = ToolRegistry(ticket)
    tools.call('get_customer_history', {'customer_id': ticket.customer.customer_id})
    tools.call('search_knowledge_base', {'query': 'HTTP 500'})
    assert [call.name for call in tools.trace if call.ok] == [
        'get_customer_history', 'search_knowledge_base',
    ]

    proposal = mock_proposal(urgency='low', action='auto_respond')
    result = finalize(ticket, proposal, tools)

    if broad_outage:
        assert (result.urgency, result.action, result.assigned_team) == (
            'critical', 'escalate_to_human', 'Infrastructure / On-call',
        )
    else:
        assert result.urgency != 'critical'


def test_dark_bug_needs_specialist(tickets):
    t = tickets["TICKET-003"]
    result = finalize(t, mock_proposal(urgency="low"), ToolRegistry(t))
    assert result.urgency == "medium"
    assert result.action == "route_to_specialist"
    assert "Scheduled dark-mode support is unverified" in result.uncertainties


def test_unverified_kb_citation_discarded_and_no_auto_response(tickets):
    t = tickets["TICKET-003"].model_copy(deep=True)
    t.messages = [Message(when="now", text="Hello, how do I get started?")]
    tools = ToolRegistry(t)
    result = finalize(t, mock_proposal(kb_article_ids=["FAKE-KB-999"]), tools)
    assert result.urgency == "low"
    assert result.kb_article_ids == []
    assert result.action == "route_to_specialist"
    assert "unverified_kb_article_ids_removed" in result.policy_overrides


def test_valid_low_risk_can_auto_respond(tickets):
    t = tickets["TICKET-003"].model_copy(deep=True)
    t.messages = [Message(when="now", text="Hello, how do I get started?")]
    tools = ToolRegistry(t)
    tools.call("search_knowledge_base", {"query": "hello getting started guide"})
    result = finalize(t, mock_proposal(kb_article_ids=["KB-004"]), tools)
    assert result.urgency == "low"
    assert result.action == "auto_respond"


def test_failed_tool_disables_auto_response(tickets):
    t = tickets["TICKET-003"].model_copy(deep=True)
    t.messages = [Message(when="now", text="Hello, how do I get started?")]
    tools = ToolRegistry(t)
    tools.call("search_knowledge_base", {"query": "hello guide"})
    tools.call("check_billing_status", {"customer_id": "wrong-customer"})
    result = finalize(t, mock_proposal(kb_article_ids=["KB-004"]), tools)
    assert result.action == "route_to_specialist"
    assert "tool_failure_prevents_auto_response" in result.policy_overrides
    assert "auto_response_replaced_with_approved_faq_template" not in result.policy_overrides
    assert result.tools_used == ["search_knowledge_base"]
    assert not result.tool_trace[-1].ok


@pytest.mark.parametrize("level,expected_action", [
    ("medium", "route_to_specialist"),
    ("high", "escalate_to_human"),
    ("critical", "escalate_to_human"),
])
def test_any_non_low_urgency_cannot_auto_respond_even_with_kb(tickets, level, expected_action):
    t = tickets["TICKET-003"].model_copy(deep=True)
    t.messages = [Message(when="now", text="Hello, can you review this account issue?")]
    tools = ToolRegistry(t)
    tools.call("search_knowledge_base", {"query": "hello general guide"})
    result = finalize(t, mock_proposal(urgency=level, kb_article_ids=["KB-004"]), tools)
    assert result.action == expected_action
    assert "auto_response_only_allowed_for_low_urgency" in result.policy_overrides
