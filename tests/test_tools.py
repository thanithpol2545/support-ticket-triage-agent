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


def test_status_feed_is_not_incident_confirmation(tickets):
    tools = ToolRegistry(tickets["TICKET-002"])
    response = tools.call("check_system_status", {"region": "Thailand"})
    assert response["region"] == "Asia"
    assert response["status"]["incident_confirmed"] is None
    assert response["status"]["public_status"] == "operational"


def test_unknown_tool_fails_closed(tickets):
    tools = ToolRegistry(tickets["TICKET-002"])
    response = tools.call("delete_user_data", {"customer_id": "cust-ent-002"})
    assert "error" in response
    assert not tools.trace[-1].ok
