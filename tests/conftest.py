import pytest
from triage_agent.agent import load_tickets


@pytest.fixture
def tickets():
    return {t.ticket_id: t for t in load_tickets()}
