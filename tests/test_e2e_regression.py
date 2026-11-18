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
