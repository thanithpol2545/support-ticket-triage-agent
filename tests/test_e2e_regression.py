"""CLI acceptance tests: the route exercised by reviewers, not just policy.finalize."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from triage_agent.agent import DemoTriageAgent, load_tickets
from triage_agent.cli import main
from triage_agent.models import Customer, Message, Ticket


CASES = json.loads((Path(__file__).resolve().parents[1] / 'evaluation' / 'adversarial_cases.json').read_text(encoding='utf-8'))


def edge_ticket(case_id: str, text: str) -> Ticket:
    return Ticket(
        ticket_id=case_id,
        customer=Customer(customer_id='test-'+case_id, plan='Enterprise', tenure_months=1),
        messages=[Message(when='now', text=text)],
    )


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_all_edge_fixtures_through_actual_cli(case, tmp_path, capsys):
    source = tmp_path / 'ticket.json'
    source.write_text(json.dumps(edge_ticket(case['id'], case['text']).model_dump(), ensure_ascii=False), encoding='utf-8')
    assert main(['--mode', 'demo', '--ticket-file', str(source), '--no-trace']) == 0
    result = json.loads(capsys.readouterr().out)[0]
    assert result['urgency'] == case['expected_urgency']
    if case['expected_action'] is not None:
        assert result['action'] == case['expected_action']
    assert {'get_customer_history', 'search_knowledge_base'} <= set(result['tools_used'])


@pytest.mark.parametrize('case_id,used_article', [('EDGE-006', 'KB-004'), ('EDGE-009', 'KB-003')])
def test_auto_response_only_cites_its_approved_article(case_id, used_article):
    case = next(candidate for candidate in CASES if candidate['id'] == case_id)
    result = DemoTriageAgent().run(edge_ticket(case_id, case['text']))

    assert (result.urgency, result.action) == ('low', 'auto_respond')
    assert result.kb_article_ids == [used_article]


@pytest.mark.parametrize('language,text', [
    ('thai-billing', 'ไม่มีการหักเงินซ้ำครับ ช่วยส่งคู่มือให้ด้วย'),
    ('thai-outage', 'ไม่ได้ขึ้น error 500 เพื่อนร่วมงานทุกคนเข้าใช้งานได้'),
    ('en-billing', 'There were no duplicate charges on my card. I only need a guide.'),
    ('en-outage', 'No HTTP 500 errors occurred. Everyone can log in.'),
    ('mixed-billing', 'ไม่มีการเรียกเก็บเงินซ้ำ / no duplicate charges. ขอ guide'),
])
def test_multilingual_negation_does_not_trigger_emergency(language, text):
    result = DemoTriageAgent().run(edge_ticket(language, text))
    assert result.urgency == 'low'
    assert result.action in {'auto_respond', 'route_to_specialist'}


@pytest.mark.parametrize('text,urgency', [
    ('We were charged twice this afternoon.', 'high'),
    ('ถูกหักเงิน 4 ครั้ง แต่บัญชีไม่ได้อัปเกรด', 'high'),
    ('There were no errors yesterday, but now our entire company cannot access production. System is down.', 'critical'),
    ('ไม่มี error 500 เมื่อวาน แต่ตอนนี้ทั้งองค์กรเข้าใช้งานไม่ได้', 'critical'),
])
def test_affirmed_incidents_still_escalate(text, urgency):
    result = DemoTriageAgent().run(edge_ticket('positive', text))
    assert result.urgency == urgency
    assert result.action == 'escalate_to_human'


def test_empty_input_is_rejected_without_success_message(tmp_path, capsys):
    source = tmp_path / 'empty.json'
    source.write_text('[]', encoding='utf-8')
    assert main(['--mode', 'demo', '--ticket-file', str(source)]) == 2
    streams = capsys.readouterr()
    assert 'No tickets to process' in streams.err
    assert streams.out == ''


def test_invalid_batch_fails_atomically(tmp_path, capsys):
    source = tmp_path / 'batch.json'
    source.write_text(json.dumps([load_tickets()[0].model_dump(), {'bad':'input'}]), encoding='utf-8')
    assert main(['--mode', 'demo', '--ticket-file', str(source)]) == 2
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('text,team', [
    ('My payment failed when I tried to upgrade to Pro.', 'Billing Support'),
    ('ชำระเงินไม่สำเร็จครับ ช่วยตรวจสอบให้ด้วย', 'Billing Support'),
    ('I cannot log in and see an HTTP 500 error.', 'Technical Support'),
])
def test_individual_failure_is_routed_not_auto_closed(text, team):
    result = DemoTriageAgent().run(edge_ticket('single-issue', text))
    assert result.urgency == 'medium'
    assert result.action == 'route_to_specialist'
    assert result.assigned_team == team


@pytest.mark.parametrize('message,http_500_reported', [
    ('ระบบเข้าไม่ได้ครับ ขึ้น error 500', True),
    ('เข้าระบบไม่ได้ครับ ขึ้น error 500', True),
    ('ใช้งานไม่ได้ครับ ขึ้น error 500', True),
    ('ระบบเข้าไม่ได้ครับ ไม่ได้ขึ้น error 500', False),
], ids=['access', 'system-access', 'usage', 'explicitly-negated-500'])
def test_thai_access_failure_preserves_separate_http_500_evidence(message, http_500_reported):
    ticket = edge_ticket('thai-http-500', message)
    ticket.messages.append(Message(when='later', text='เพื่อนร่วมงานก็เข้าไม่ได้เหมือนกัน'))

    result = DemoTriageAgent().run(ticket)

    assert result.urgency == 'critical'
    assert 'access_failure' in result.issue_types
    assert ('http_500' in result.issue_types) == http_500_reported


@pytest.mark.parametrize('messages,urgency,action,team', [
    (['No problem but I was charged twice. Need help.'], 'high', 'escalate_to_human', 'Billing Support'),
    (['No issue before but now HTTP 500 for all employees.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['ก่อนหน้านี้ไม่มี error แต่ตอนนี้ทุกคนเข้าใช้งานไม่ได้'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['Everyone else can log in and I get HTTP 500.'], 'medium', 'route_to_specialist', 'Technical Support'),
    (['Everyone else can log in.', 'I get HTTP 500.'], 'medium', 'route_to_specialist', 'Technical Support'),
    (['I get HTTP 500.', 'Coworkers are not getting the same error.'], 'medium', 'route_to_specialist', 'Technical Support'),
    (['I get HTTP 500.', 'My coworkers are getting the same error.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['I get HTTP 500. My coworkers got the same error.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['I get HTTP 500.', 'Same error for my coworkers.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['My account got HTTP 500. None of our coworkers have HTTP 500.'], 'medium', 'route_to_specialist', 'Technical Support'),
    (['The system is down and everyone at the office is affected.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['The service is down company-wide.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['All employees in Asia cannot access production.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['All employees in Asia can log in and I get HTTP 500.'], 'medium', 'route_to_specialist', 'Technical Support'),
    (['No one can log in.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['Nobody in the London office can log in.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['None of my colleagues can log in.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['All employees in Asia are not seeing HTTP 500. I am the only one who cannot log in.'], 'medium', 'route_to_specialist', 'Technical Support'),
    (['Everyone at our office is not seeing HTTP 500. I am the only person affected.'], 'low', 'route_to_specialist', 'General Support'),
    (['All employees in our London office are seeing HTTP 500.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['All users and employees cannot sign in.'], 'critical', 'escalate_to_human', 'Infrastructure / On-call'),
    (['Billing denied my refund.', 'I dispute that decision.'], 'high', 'escalate_to_human', 'Billing Support'),
])
def test_cli_distinguishes_affirmed_incidents_from_unrelated_context(messages, urgency, action, team, tmp_path, capsys):
    ticket = edge_ticket('context', messages[0])
    ticket.messages = [Message(when=str(i), text=text) for i, text in enumerate(messages)]
    source = tmp_path / 'context.json'
    source.write_text(ticket.model_dump_json(), encoding='utf-8')

    assert main(['--ticket-file', str(source), '--no-trace']) == 0
    result = json.loads(capsys.readouterr().out)[0]
    assert (result['urgency'], result['action'], result['assigned_team']) == (urgency, action, team)



@pytest.mark.parametrize(
    'message,urgency,action,team',
    [
        pytest.param(
            'All users get HTTP 500.', 'critical', 'escalate_to_human',
            'Infrastructure / On-call', id='group-first',
        ),
        pytest.param(
            'HTTP 500 affects all users.', 'critical', 'escalate_to_human',
            'Infrastructure / On-call', id='affects',
        ),
        pytest.param(
            'HTTP 500 is affecting all users.', 'critical', 'escalate_to_human',
            'Infrastructure / On-call', id='is-affecting',
        ),
        pytest.param(
            'I get HTTP 500. Everyone else can log in.', 'medium', 'route_to_specialist',
            'Technical Support', id='only-one-user',
        ),
        pytest.param(
            'No HTTP 500 occurred. Everyone can log in.', 'low', None, None,
            id='no-error',
        ),
        pytest.param(
            'HTTP 500 does not affect all users.', None, None, None,
            id='not-all-users',
        ),
        pytest.param(
            "I don't think HTTP 500 affects all users. Only I get the error.", None, None, None,
            id='doubt-about-scope',
        ),
        pytest.param(
            'HTTP 500 affects all users? Everyone can log in.', None, None, None,
            id='asks-about-scope',
        ),
        pytest.param(
            'HTTP 500 affects all our users. Can you check?', 'critical', 'escalate_to_human',
            'Infrastructure / On-call', id='affirmed-before-question',
        ),
        pytest.param(
            'All users get HTTP 500 can you help?', 'critical', 'escalate_to_human',
            'Infrastructure / On-call', id='group-first-with-help-question',
        ),
    ],
)
def test_cli_outage_impact_controls_routing_and_status_tool(
    tickets, message, urgency, action, team, tmp_path, capsys,
):
    ticket = tickets['TICKET-002'].model_copy(update={'messages': [Message(when='now', text=message)]})
    source = tmp_path / 'impact.json'
    source.write_text(ticket.model_dump_json(), encoding='utf-8')

    assert main(['--mode', 'demo', '--ticket-file', str(source)]) == 0
    result = json.loads(capsys.readouterr().out)[0]
    status_calls = [call for call in result['tool_trace'] if call['name'] == 'check_system_status']

    if urgency is None:
        assert result['urgency'] != 'critical'
    else:
        assert result['urgency'] == urgency
    if action is not None:
        assert (result['action'], result['assigned_team']) == (action, team)
    elif urgency == 'low':
        assert result['action'] != 'escalate_to_human'

    if urgency == 'critical':
        assert any(call['ok'] for call in status_calls)
    else:
        assert not status_calls


def test_joint_incident_checks_billing_and_status_without_inventing_incident_details():
    ticket = edge_ticket('joint', 'My card was charged twice. Our entire company cannot access production.')
    ticket.customer.region = 'Europe'
    result = DemoTriageAgent().run(ticket)

    assert result.urgency == 'critical'
    assert result.assigned_team == 'Infrastructure / On-call'
    assert set(result.issue_types) == {'access_failure', 'repeated_charges_reported'}
    assert {'check_billing_status', 'check_system_status'} <= set(result.tools_used)
    assert result.tool_trace[-1].arguments == {'region': 'Europe'}
    assert 'Billing Support' in result.draft_response
    assert 'Asia' not in result.draft_response
    assert 'demo' not in result.summary.lower()


def test_long_ticket_keeps_late_billing_evidence():
    text = 'Could you send me the guide? ' * 100 + 'But now my card was charged twice.'
    result = DemoTriageAgent().run(edge_ticket('long', text))
    assert result.urgency == 'high'
    assert result.action == 'escalate_to_human'
    kb_trace = next(event for event in result.tool_trace if event.name == 'search_knowledge_base')
    assert kb_trace.ok and len(kb_trace.arguments['query']) <= 2000


def test_refund_status_question_is_not_a_refund_dispute():
    result = DemoTriageAgent().run(edge_ticket('refund-question', 'How can I check the status of my refund?'))
    assert result.urgency == 'low'
    assert 'check_billing_status' not in result.tools_used
