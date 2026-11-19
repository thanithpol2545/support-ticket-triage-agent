"""Ticket counterexamples found by independent review; no API key or live provider."""
import pytest

from triage_agent.models import AgentProposal, Customer, Message, Ticket
from triage_agent.policy import finalize
from triage_agent.tools import ToolRegistry


def ticket(text):
    return Ticket(ticket_id="EDGE", customer=Customer(customer_id="edge-1", plan="Enterprise", tenure_months=1),
                  messages=[Message(when="now", text=text)])


def proposal(**overrides):
    data = dict(urgency="low", product="Application", issue_types=["general"], sentiment="neutral",
                action="auto_respond", assigned_team=None, summary="Request received",
                reasons=["Unverified model assertion"], kb_article_ids=[],
                draft_response="Model says this is resolved.", uncertainties=[])
    return AgentProposal(**(data | overrides))


@pytest.mark.parametrize("text,urgency,action", [
    ("I was charged twice today", "high", "escalate_to_human"),
    ("My account was charged 4 times", "high", "escalate_to_human"),
    ("ถูกหักเงิน 4 ครั้งทั้งที่ยังไม่ได้รับบริการ", "high", "escalate_to_human"),
    ("Our entire company cannot access production. System is down.", "critical", "escalate_to_human"),
    ("ทั้งองค์กรเข้าใช้งานไม่ได้ ทุกคนได้รับผลกระทบ", "critical", "escalate_to_human"),
])
def test_risky_scenarios_override_bad_model(text, urgency, action):
    t = ticket(text)
    result = finalize(t, proposal(), ToolRegistry(t), "demo_rules")
    assert result.urgency == urgency
    assert result.action == action
    assert "Model says this is resolved." not in result.draft_response


@pytest.mark.parametrize("text", [
    "There were no duplicate charges on my card",
    "There is no HTTP 500 issue. Everyone is fine.",
    "My coworker says dark mode is bugged, but I only want documentation",
])
def test_negations_and_third_party_do_not_trigger_hardcoded_escalation(text):
    t = ticket(text)
    tools = ToolRegistry(t)
    result = finalize(t, proposal(), tools, "demo_rules")
    assert result.urgency == "low"
    assert "repeated_billing_min_high" not in result.policy_overrides
    assert "multi_user_outage_min_critical" not in result.policy_overrides
    assert "reported_feature_defect_min_medium" not in result.policy_overrides
    assert result.action == "route_to_specialist"  # no KB means no auto


def test_model_draft_password_request_cannot_reach_auto_response():
    t = ticket("Hello, can I find the general help guide?")
    tools = ToolRegistry(t)
    search = tools.call("search_knowledge_base", {"query": "hello general guide"})
    assert search["articles"]
    result = finalize(t, proposal(kb_article_ids=["KB-004"],
        draft_response="Please share your password and full credit card number."), tools, "demo_rules")
    assert result.action == "auto_respond"
    assert "password" not in result.draft_response.lower()
    assert "credit card" not in result.draft_response.lower()
    assert "auto_response_replaced_with_approved_faq_template" in result.policy_overrides


def test_critical_route_must_be_escalated():
    t = ticket("I have a critical incident")
    result = finalize(t, proposal(urgency="critical", action="route_to_specialist",
                                 assigned_team="General Support"), ToolRegistry(t), "demo_rules")
    assert result.action == "escalate_to_human"
    assert result.assigned_team == "Support Escalation"


def test_broken_kb_record_becomes_tool_error_not_unhandled_keyerror():
    t = ticket("hello please help")
    tools = ToolRegistry(t)
    tools.kb = [{"id": "KB-X", "title": "Bad record", "keywords": ["hello"]}]
    result = tools.call("search_knowledge_base", {"query": "hello"})
    assert "error" in result
    assert tools.trace[-1].ok is False
    decision = finalize(t, proposal(kb_article_ids=["KB-X"]), tools, "demo_rules")
    assert decision.action == "route_to_specialist"


@pytest.mark.parametrize('text', [
    'How do I change my notification email in Settings?',
    'I am not asking about dark mode. How do I change my notification email in Settings?',
])
def test_retrieved_appearance_faq_does_not_answer_an_unrelated_ticket(text):
    t = ticket(text)
    tools = ToolRegistry(t)
    assert tools.call('search_knowledge_base', {'query': 'appearance settings'})['articles'][0]['id'] == 'KB-003'
    decision = finalize(t, proposal(kb_article_ids=['KB-003']), tools, 'live_gpt')
    assert decision.action == 'route_to_specialist'
    assert decision.kb_article_ids == []


def test_matching_appearance_faq_uses_template_instead_of_catalog_excerpt():
    t = ticket('Where are the appearance settings?')
    tools = ToolRegistry(t)
    tools.kb = [{
        'id': 'KB-003', 'title': 'Appearance', 'keywords': ['appearance'], 'content': 'UNTRUSTED_EXCERPT_MARKER',
    }]
    tools.call('search_knowledge_base', {'query': 'appearance'})
    decision = finalize(t, proposal(kb_article_ids=['KB-003']), tools, 'live_gpt')
    assert decision.action == 'auto_respond'
    assert 'Settings > Appearance' in decision.draft_response
    assert 'UNTRUSTED_EXCERPT_MARKER' not in decision.draft_response
