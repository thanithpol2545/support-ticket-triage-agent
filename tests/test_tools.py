import pytest

from triage_agent.tools import ToolRegistry, TOOL_SCHEMAS


def test_tools_have_valid_strict_json_schemas():
    assert len(TOOL_SCHEMAS) >= 2
    for tool in TOOL_SCHEMAS:
        assert tool["strict"] is True
        assert tool["parameters"]["additionalProperties"] is False
        assert set(tool["parameters"]["properties"]) == set(tool["parameters"]["required"])


def test_customer_scope_blocks_cross_customer_reads(tickets):
    tools = ToolRegistry(tickets["TICKET-001"])
    result = tools.call("check_billing_status", {"customer_id": "cust-ent-002"})
    assert "error" in result
    assert not tools.trace[-1].ok


def test_kb_returns_source_ids_for_thai_and_english(tickets):
    tools = ToolRegistry(tickets["TICKET-002"])
    result = tools.call("search_knowledge_base", {"query": "ระบบเข้าไม่ได้ error 500 Asia"})
    assert "KB-002" in [a["id"] for a in result["articles"]]
    assert "KB-002" in tools.valid_article_ids()


def test_no_match_does_not_invent_article(tickets):
    tools = ToolRegistry(tickets["TICKET-001"])
    r = tools.call("search_knowledge_base", {"query": "quasar-nonexistent-keyword"})
    assert r["articles"] == []


@pytest.mark.parametrize('region', ['Thailand', 'asia', 'ASIA'])
def test_status_feed_is_not_incident_confirmation(tickets, region):
    tools = ToolRegistry(tickets["TICKET-002"])
    response = tools.call("check_system_status", {"region": region})
    assert response["region"] == "Asia"
    assert response["status"]["incident_confirmed"] is None
    assert response["status"]["public_status"] == "operational"


def test_unknown_tool_fails_closed(tickets):
    tools = ToolRegistry(tickets["TICKET-002"])
    response = tools.call("delete_user_data", {"customer_id": "cust-ent-002"})
    assert "error" in response
    assert not tools.trace[-1].ok


@pytest.mark.parametrize('overrides', [{'id': []}, {'keywords': 'appearance'}, {'content': 42}, None])
def test_kb_rejects_invalid_fields_and_conflicting_article_ids(tickets, overrides):
    tools = ToolRegistry(tickets['TICKET-003'])
    article = {'id': 'KB-003', 'title': 'Appearance', 'keywords': ['appearance'], 'content': 'First excerpt'}
    tools.kb = [article | overrides] if overrides is not None else [article, article | {'content': 'Conflicting excerpt'}]

    assert tools.call('search_knowledge_base', {'query': 'appearance'})['source'] == 'tool_error'
    assert tools.valid_article_ids() == set()


def test_invalid_tool_argument_error_does_not_echo_input(tickets):
    tools = ToolRegistry(tickets['TICKET-003'])
    result = tools.call('search_knowledge_base', {'query': ['PRIVATE_TEST_MARKER']})
    assert result['source'] == 'tool_error'
    assert 'PRIVATE_TEST_MARKER' not in str(result)
