import json

import pytest

from evaluation.paired import load_pairs, ticket_for
from triage_agent import tools
from triage_agent.cli import main
from triage_agent.models import Message


PAIRS = {pair["id"]: pair for pair in load_pairs()}


@pytest.fixture
def run_audit(mock_openai, tmp_path, capsys):
    def run(ticket, **proposal_fields):
        path = tmp_path / "ticket.json"
        path.write_text(ticket.model_dump_json(), encoding="utf-8")
        mock_openai.queue(ticket, **proposal_fields)
        assert main(["--ticket-file", str(path), "--audit"]) == 0
        return json.loads(capsys.readouterr().out)[0]

    return run


@pytest.mark.parametrize(
    "action,team",
    [("auto_respond", None), ("route_to_specialist", "Technical Support"),
     ("escalate_to_human", "Support Escalation")],
)
@pytest.mark.parametrize(
    "request_text",
    ["Please provide us with your password.", "Could you confirm your account password so we can update your email?",
     "What is the password you use to sign in?", "May I have your account password so I can troubleshoot?",
     "Reset your password. Then send it to us.", "Reset your password. Then email it to our support team.",
     "Never share your password, except with support."],
    ids=["provide-password", "confirm-password", "ask-for-password", "ask-to-have-password", "disclosure-after-reset",
         "email-after-reset", "warning-with-exception"],
)
def test_audit_password_request_is_removed_from_every_final_action(action, team, request_text, run_audit):
    ticket = ticket_for(PAIRS["P08"], "A")
    audit = run_audit(
        ticket, action=action, assigned_team=team,
        draft_response=request_text, kb_article_ids=["KB-004"],
    )

    assert audit["proposal"]["draft_response"] == request_text
    final = audit["result"]
    assert (final["action"], final["assigned_team"]) == (action, team)
    assert request_text not in final["draft_response"]
    if action == "auto_respond":
        assert "auto_response_replaced_with_approved_faq_template" in final["policy_overrides"]
    else:
        assert "do not share your password" in final["draft_response"].lower()
        assert "password_request_replaced_with_safe_draft" in final["policy_overrides"]


@pytest.mark.parametrize("action", ["route_to_specialist", "escalate_to_human"])
@pytest.mark.parametrize(
    "draft", ["Please never share your password.", "You can reset your password from your account settings.",
              "Change your login password in your account settings. Never reveal your password."],
    ids=["warning", "self-service-reset", "self-service-and-warning"],
)
def test_audit_preserves_safe_password_guidance_on_handoff(action, draft, run_audit):
    ticket = ticket_for(PAIRS["P08"], "B")
    final = run_audit(ticket, action=action, assigned_team="Technical Support", draft_response=draft)["result"]

    assert final["draft_response"] == draft
    assert "password_request_replaced_with_safe_draft" not in final["policy_overrides"]


@pytest.mark.parametrize(
    "updates,required,forbidden",
    [
        pytest.param(
            ["Everyone in Europe can log in again."],
            ["users in Europe can access the system again", "whether access has been restored in Asia remains unconfirmed"],
            ["users in Asia can access the system again"], id="other-region-recovery",
        ),
        pytest.param(
            ["Everyone in Asia can log in again."],
            ["can access the system again"], ["cannot access"], id="same-region-recovery",
        ),
        pytest.param(
            ["Everyone in Asia can log in again.", "All users in Asia get HTTP 500 again."],
            ["cannot access"], ["can access the system again"], id="same-region-relapse",
        ),
        pytest.param(
            ["All staff in Europe cannot sign in.", "The service in Europe is back online.",
             "Everyone in Asia can log in again.", "All staff in Europe get HTTP 500 again."],
            ["users in Asia can access the system again", "latest report for Europe says users could not access"],
            ["users in Europe can access the system again"], id="relapse-after-two-regions-recover",
        ),
    ],
)
def test_audit_outage_draft_tracks_recovery_scope_and_order(updates, required, forbidden, run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages.extend(Message(when=str(index), text=text) for index, text in enumerate(updates, 2))
    proposal_draft = "Thanks for confirming that Asia recovered."
    audit = run_audit(ticket, draft_response=proposal_draft, action="route_to_specialist")

    assert audit["proposal"]["draft_response"] == proposal_draft
    draft = audit["result"]["draft_response"].lower()
    for fragment in required:
        assert fragment.lower() in draft
    for fragment in forbidden:
        assert fragment.lower() not in draft


@pytest.mark.parametrize(
    "outage,recovery,affected,recovered",
    [
        ("All employees in Thailand cannot sign in.", "All employees in Germany can sign in again.", "Thailand", "Germany"),
        ("In Singapore all employees cannot sign in.", "In Japan all staff can sign in again.", "Singapore", "Japan"),
        ("In Singapore, all employees cannot sign in.", "In Japan, all staff can sign in again.", "Singapore", "Japan"),
        ("Singapore: all employees cannot sign in.", "Japan: all staff can sign in again.", "Singapore", "Japan"),
        ("Cebu office: currently all staff cannot sign in.", "Taipei office: now all staff can sign in again.",
         "Cebu office", "Taipei office"),
        ("Jakarta office:\nCurrently all staff cannot sign in.", "Seoul office:\nNow all staff can sign in again.",
         "Jakarta office", "Seoul office"),
        ("Osaka office:\nAs of 10:30, all staff cannot sign in.", "Manila office:\nAs of 11:00, all staff can sign in again.",
         "Osaka office", "Manila office"),
        ("Cebu office:\nImpact: all staff cannot sign in.", "Taipei office:\nRecovery: all staff can sign in again.",
         "Cebu office", "Taipei office"),
        ("Cebu office:\nAffected users: all staff cannot sign in.", "Taipei office:\nResolution: all staff can sign in again.",
         "Cebu office", "Taipei office"),
        ("Cebu office:\nObservations: all staff cannot sign in.\nTaipei office: all staff can sign in again.",
         None, "Cebu office", "Taipei office"),
        ("Bangkok:\nAll staff cannot sign in.\nTokyo:\nAll staff can sign in again.", None, "Bangkok", "Tokyo"),
        ("Sapporo office:\nCustomer report:\nAll staff cannot sign in.\nOsaka office:\nRecovery notes:\nAll staff can sign in again.",
         None, "Sapporo office", "Osaka office"),
        ("Chiang Mai office:\nCurrent status:\nAll staff cannot sign in.",
         "Hanoi office:\nRecovery status:\nAll staff can sign in again.", "Chiang Mai office", "Hanoi office"),
    ],
    ids=["location-after-group", "location-before-group", "location-before-group-with-comma", "location-as-heading",
         "location-heading-with-time-modifier", "location-heading-on-separate-line", "location-heading-before-timestamp",
         "location-with-incident-subheading", "location-with-alternative-subheading", "location-with-custom-field-and-new-section",
         "standalone-location-headings-in-one-message", "standalone-incident-fields-in-one-message",
         "standalone-status-fields-in-separate-messages"],
)
def test_audit_outage_draft_does_not_merge_different_countries(outage, recovery, affected, recovered, run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [Message(when="1", text=outage)]
    if recovery is not None:
        ticket.messages.append(Message(when="2", text=recovery))
    audit = run_audit(ticket, draft_response="Thanks for confirming the outage is resolved.", action="route_to_specialist")
    draft = audit["result"]["draft_response"].lower()

    assert f"users in {recovered.lower()} can access the system again" in draft
    assert f"whether access has been restored in {affected.lower()} remains unconfirmed" in draft
    assert f"users in {affected.lower()} can access the system again" not in draft


@pytest.mark.parametrize(
    "text,is_outage",
    [
        pytest.param(
            "If the service is down, all users cannot log in. What is the procedure?",
            False, id="hypothetical-across-comma",
        ),
        pytest.param(
            "All users cannot log in. What is the procedure?", True, id="affirmed-before-question",
        ),
        pytest.param(
            "All users in Asia get HTTP 500 right now and I need to know if there is a runbook.",
            True, id="affirmed-before-coordinated-question",
        ),
        pytest.param(
            "All users in Europe are getting HTTP 500 right now and please let me know if I should page on-call.",
            True, id="affirmed-before-coordinated-indirect-question",
        ),
        pytest.param(
            "All users in Europe get HTTP 500 and please advise if we should page on-call.",
            True, id="affirmed-before-coordinated-request-for-advice",
        ),
        pytest.param(
            "All users in Europe are getting HTTP 500 right now - can you check if we should page on-call?",
            True, id="affirmed-before-dashed-question",
        ),
        pytest.param(
            "If the system goes down — all staff cannot log in. Who is on-call?",
            False, id="hypothetical-across-dash",
        ),
        pytest.param(
            "All users in Asia get HTTP 500 — if the service goes down. Who is on-call?",
            False, id="hypothetical-if-after-dash",
        ),
        pytest.param(
            "Everyone in Europe gets HTTP 500 — assuming the login service goes offline. Who would be paged?",
            False, id="hypothetical-assumption-after-dash",
        ),
        pytest.param(
            "All users in Asia are getting HTTP 500 — if you're on call, can you check?",
            True, id="affirmed-before-conditional-request",
        ),
        pytest.param(
            "All users in Europe are getting HTTP 500 — if the regional on-call is unavailable, send this to the backup team.",
            True, id="affirmed-before-conditional-instruction",
        ),
        pytest.param(
            "All users in Europe are getting HTTP 500 — if the lead is unavailable, hand this to the backup responder.",
            True, id="affirmed-before-conditional-handoff",
        ),
        pytest.param(
            "All users in Europe are getting HTTP 500 — if the primary responder is unavailable, reach out to the backup.",
            True, id="affirmed-before-phrasal-handoff",
        ),
        pytest.param(
            "All users in Asia get HTTP 500 — if the service goes down, right?",
            False, id="hypothetical-before-confirmation-tag",
        ),
        pytest.param(
            "All users in Asia get HTTP 500 — if the login gateway goes offline, then the entire team will be locked out.",
            False, id="hypothetical-before-declarative-consequence",
        ),
        pytest.param(
            "All users in Asia get HTTP 500, but only if the service goes down. Who is on-call?",
            False, id="hypothetical-but-only-if-after-comma",
        ),
        pytest.param(
            "All users get HTTP 500 if the service is down. What is the procedure?",
            False, id="hypothetical-following-its-consequence",
        ),
    ],
)
def test_audit_outage_policy_distinguishes_condition_from_report(text, is_outage, run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [Message(when="now", text=text)]
    audit = run_audit(ticket, urgency="low", action="route_to_specialist", assigned_team="General Support")

    assert audit["proposal"]["urgency"] == "low"
    final = audit["result"]
    if is_outage:
        assert (final["urgency"], final["action"], final["assigned_team"]) == (
            "critical", "escalate_to_human", "Infrastructure / On-call",
        )
    else:
        assert (final["urgency"], final["action"], final["assigned_team"]) == (
            "low", "route_to_specialist", "General Support",
        )


@pytest.mark.parametrize(
    "query,citations,action",
    [
        ("settings", [], "route_to_specialist"),
        ("settings help", ["KB-004"], "auto_respond"),
    ],
)
def test_audit_p11a_removes_unrelated_appearance_guidance(query, citations, action, run_audit):
    ticket = ticket_for(PAIRS["P11"], "A")
    audit = run_audit(
        ticket, query=query, kb_article_ids=["KB-003", *citations],
        draft_response="Open Settings > Appearance.",
    )

    assert audit["proposal"]["action"] == "auto_respond"
    final = audit["result"]
    search = final["tool_trace"][1]
    assert search["ok"]
    assert "KB-003" in [article["id"] for article in search["result"]["articles"]]
    assert final["kb_article_ids"] == citations
    assert final["action"] == action
    assert "appearance" not in final["draft_response"].lower()


@pytest.mark.parametrize(
    "action,team,query,retrieved",
    [
        ("route_to_specialist", "Technical Support", "settings", True),
        ("escalate_to_human", "Support Escalation", "settings", True),
        ("route_to_specialist", "Technical Support", "notification preferences", False),
    ],
    ids=["specialist", "escalation", "unretrieved-citation"],
)
def test_audit_p11a_replaces_handoff_draft_that_cites_appearance(action, team, query, retrieved, run_audit):
    proposal_draft = "Open Settings > Appearance."
    audit = run_audit(
        ticket_for(PAIRS["P11"], "A"), query=query, action=action, assigned_team=team,
        kb_article_ids=["KB-003"], draft_response=proposal_draft,
    )

    assert audit["proposal"]["draft_response"] == proposal_draft
    assert audit["proposal"]["kb_article_ids"] == ["KB-003"]
    final = audit["result"]
    search = final["tool_trace"][1]
    assert search["ok"]
    assert ("KB-003" in [article["id"] for article in search["result"]["articles"]]) is retrieved
    assert (final["action"], final["assigned_team"]) == (action, team)
    assert final["kb_article_ids"] == []
    assert "appearance" not in final["draft_response"].lower()
    assert "review your question" in final["draft_response"].lower()
    assert "handoff_draft_replaced_after_appearance_faq_rejection" in final["policy_overrides"]


@pytest.mark.parametrize("action,team", [("route_to_specialist", "Product Support"), ("auto_respond", None)])
def test_audit_p11b_keeps_relevant_appearance_guidance(action, team, run_audit):
    proposal_draft = "Open Settings > Appearance."
    audit = run_audit(
        ticket_for(PAIRS["P11"], "B"), query="settings", action=action, assigned_team=team,
        kb_article_ids=["KB-003"], draft_response=proposal_draft,
    )

    final = audit["result"]
    assert (final["action"], final["assigned_team"]) == (action, team)
    assert final["kb_article_ids"] == ["KB-003"]
    if action == "auto_respond":
        assert "Settings > Appearance" in final["draft_response"]
        assert "auto_response_replaced_with_approved_faq_template" in final["policy_overrides"]
    else:
        assert final["draft_response"] == proposal_draft


@pytest.mark.parametrize("case_id", ["P01A", "P01B", "P02A", "P02B", "P03A", "P03B", "P08A", "P08B"])
def test_paired_regression_through_cli(case_id, mock_openai, tmp_path, capsys):
    pair = PAIRS[case_id[:-1]]
    side = case_id[-1]
    ticket = ticket_for(pair, side)
    path = tmp_path / "ticket.json"
    path.write_text(ticket.model_dump_json(), encoding="utf-8")

    draft = pair.get("draft", {}).get(side, "Thank you for the update.")
    if case_id in {"P02B", "P03A"}:
        draft = "Thanks for letting us know that everyone can access the app again."
    mock_openai.queue(
        ticket, query="HTTP 500 access", draft_response=draft,
        action="route_to_specialist", assigned_team="Technical Support",
    )
    assert main(["--ticket-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)[0]

    if case_id == "P01A":
        assert result["urgency"] != "critical"
        assert result["action"] != "escalate_to_human"
        assert result["draft_response"] == draft
    elif case_id in {"P01B", "P02A", "P03B"}:
        assert (result["urgency"], result["action"], result["assigned_team"]) == (
            "critical", "escalate_to_human", "Infrastructure / On-call",
        )
        assert "cannot access" in result["draft_response"]
    elif case_id in {"P02B", "P03A"}:
        assert "can access" in result["draft_response"]
        assert "cannot access" not in result["draft_response"]
    else:
        assert (result["action"], result["assigned_team"]) == ("route_to_specialist", "Technical Support")
        if case_id == "P08A":
            assert "Please send us your password" not in result["draft_response"]
            assert "do not share your password" in result["draft_response"]
            assert "password_request_replaced_with_safe_draft" in result["policy_overrides"]
        else:
            assert result["draft_response"] == draft


@pytest.mark.parametrize("side", ["A", "B"], ids=["P12A", "P12B"])
def test_public_status_does_not_confirm_or_disprove_tenant_outage(
    side, mock_openai, monkeypatch, tmp_path, capsys,
):
    pair = PAIRS["P12"]
    ticket = ticket_for(pair, side)
    path = tmp_path / "ticket.json"
    path.write_text(ticket.model_dump_json(), encoding="utf-8")
    load_data = tools.load_data

    def load_with_public_status(filename):
        data = load_data(filename)
        if filename == "system_status.json":
            data["Asia"]["public_status"] = pair["public_status"][side]
        return data

    monkeypatch.setattr(tools, "load_data", load_with_public_status)
    mock_openai.queue(
        ticket, optional_calls=[("check_system_status", {"region": "Asia"})],
    )
    assert main(["--ticket-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)[0]
    assert (result["urgency"], result["action"], result["assigned_team"]) == (
        "critical", "escalate_to_human", "Infrastructure / On-call",
    )
    assert "Regional incident not confirmed" in result["uncertainties"]
    status = result["tool_trace"][-1]["result"]["status"]
    assert status["public_status"] == pair["public_status"][side]
    assert status["incident_confirmed"] is None


@pytest.mark.parametrize(
    "messages,expected",
    [
        pytest.param(
            ["My login page returns HTTP 500. I have not heard from the rest of the team yet."],
            ("medium", "route_to_specialist", "Technical Support"), id="only-one-reporter",
        ),
        pytest.param(
            ["I get HTTP 500.", "The two team leads reported that nobody in either group can open the login page."],
            ("critical", "escalate_to_human", "Infrastructure / On-call"), id="two-groups-confirm",
        ),
        pytest.param(
            ["ทุกคนในทีมเชียงใหม่เข้าใช้งานไม่ได้ ขึ้น HTTP 500", "หน้า status ขึ้นปกติค่ะ"],
            ("critical", "escalate_to_human", "Infrastructure / On-call"), id="local-impact-green-status",
        ),
    ],
)
def test_audit_access_routing_uses_reported_scope(messages, expected, run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [Message(when=str(i), text=text) for i, text in enumerate(messages)]
    final = run_audit(
        ticket, urgency="high", action="escalate_to_human", assigned_team="Proposed Incident Team",
        query="HTTP 500 access", kb_article_ids=["KB-002"],
        optional_calls=[("check_system_status", {"region": "Asia"})],
    )["result"]

    assert (final["urgency"], final["action"], final["assigned_team"]) == expected
    if expected[0] == "critical":
        assert "regional scope" in final["draft_response"].lower()
        assert "asia is down" not in final["draft_response"].lower()


def test_audit_denied_error_does_not_override_documentation_request(run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [
        Message(when="1", text="Nobody on our team is seeing HTTP 500 and we can all sign in."),
        Message(when="2", text="Where can I get the general documentation?"),
    ]
    final = run_audit(ticket, query="general documentation onboarding checklist", kb_article_ids=["KB-004"])["result"]

    assert (final["urgency"], final["action"], final["kb_article_ids"]) == ("low", "auto_respond", ["KB-004"])
    assert "relevant help documentation" in final["draft_response"].lower()


@pytest.mark.parametrize(
    "messages,required,forbidden",
    [
        pytest.param(
            ["เมื่อเช้าทั้งสาขาเข้าไม่ได้ ขึ้น HTTP 500", "ตอนนี้ทุกคนในสาขาเข้าได้ตามปกติแล้วค่ะ"],
            ["can access the system again"], ["cannot access"], id="branch-recovers",
        ),
        pytest.param(
            ["All users in Hanoi and all users in Cebu are blocked by HTTP 500.",
             "Hanoi is back online for everyone. Cebu is still blocked for everyone and still sees HTTP 500."],
            ["users in Hanoi can access the system again", "latest report for Cebu"],
            ["users in Cebu can access the system again"], id="separate-regional-states",
        ),
        pytest.param(
            ["All users in Asia can sign in and all users in Europe see HTTP 500."],
            ["users in Europe cannot access"], ["Asia cannot access"], id="separate-subjects-with-distinct-predicates",
        ),
    ],
)
def test_audit_access_draft_preserves_the_latest_scope(messages, required, forbidden, run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [Message(when=str(i), text=text) for i, text in enumerate(messages)]
    final = run_audit(ticket, query="HTTP 500 access", kb_article_ids=["KB-002"])["result"]

    draft = final["draft_response"].lower()
    for phrase in required:
        assert phrase.lower() in draft
    for phrase in forbidden:
        assert phrase.lower() not in draft


@pytest.mark.parametrize("statement", ["", "เปิด statement แล้วค่ะ มีรายการของร้านคุณสองบรรทัด"], ids=["retry", "reported-entries"])
def test_audit_billing_distinguishes_retry_from_statement_entries(statement, run_audit):
    ticket = ticket_for(PAIRS["P05"], "A")
    messages = ["อัปเกรดไม่ผ่านค่ะ จึงแตะยืนยันจ่ายไปรอบที่สอง"]
    if statement:
        messages.append(statement)
    ticket.messages = [Message(when=str(i), text=text) for i, text in enumerate(messages)]
    final = run_audit(
        ticket, query="upgrade failure payment", kb_article_ids=["KB-001"],
        optional_calls=[("check_billing_status", {"customer_id": ticket.customer.customer_id})],
    )["result"]

    if statement:
        assert (final["urgency"], final["action"], final["assigned_team"]) == (
            "high", "escalate_to_human", "Billing Support",
        )
        assert "pending verification" in final["draft_response"].lower()
    else:
        assert "attempted to pay 2 times" in final["summary"].lower()
        assert "not verified whether any of those attempts resulted in a charge" in final["draft_response"].lower()


@pytest.mark.parametrize(
    "updates,withdrawn",
    [(["Please close my appeal."], True), (["Please close my appeal.", "I dispute the decision again."], False)],
    ids=["withdrawn", "renewed"],
)
def test_audit_refund_handoff_uses_latest_appeal_position(updates, withdrawn, run_audit):
    ticket = ticket_for(PAIRS["P06"], "A")
    messages = ["Finance rejected my refund request. I'd like to challenge that.", *updates]
    ticket.messages = [Message(when=str(i), text=text) for i, text in enumerate(messages)]
    final = run_audit(
        ticket, query="refund rejection appeal", kb_article_ids=["KB-001"],
        draft_response="We have closed the appeal and issued the refund.",
    )["result"]

    if withdrawn:
        assert "withdraw" in final["summary"].lower()
        assert "want to withdraw" in final["draft_response"].lower()
        assert "cannot confirm" in final["draft_response"].lower()
    else:
        assert (final["urgency"], final["action"], final["assigned_team"]) == (
            "high", "escalate_to_human", "Billing Support",
        )


@pytest.mark.parametrize("relapsed", [False, True], ids=["recovered", "relapsed"])
def test_audit_appearance_handoff_uses_latest_theme_status(relapsed, run_audit):
    ticket = ticket_for(PAIRS["P07"], "B")
    messages = ["เลือก System Default แล้วแอปยังเป็นธีมสว่างค่ะ",
                "หลังรีสตาร์ตแอป ตอนนี้ธีมมืดทำงานปกติแล้วค่ะ"]
    if relapsed:
        messages.append("ตอนนี้แอปกลับมาแสดงธีมสว่างอีกครั้ง ใช้โหมดมืดไม่ได้")
    ticket.messages = [Message(when=str(i), text=text) for i, text in enumerate(messages)]
    final = run_audit(ticket, query="appearance dark mode", kb_article_ids=["KB-003"])["result"]

    if relapsed:
        assert final["urgency"] == "medium"
        assert (final["action"], final["assigned_team"]) == ("route_to_specialist", "Product Support")
        assert "working again" not in final["draft_response"].lower()
    else:
        assert final["urgency"] == "low"
        assert "working again" in final["summary"].lower()
        assert "working again" in final["draft_response"].lower()


@pytest.mark.parametrize(
    "messages,expected_scope",
    [
        pytest.param(
            ["เมื่อเช้าทีมลำปางกับทีมอุดรธานีล็อกอินไม่ได้กันทั้งสองทีม ขึ้น HTTP 500",
             "ทีมลำปางกลับเข้าได้ครบแล้ว แต่ที่อุดรธานีทุกคนยังล็อกอินไม่ได้ ขึ้น HTTP 500"],
            ("ลำปาง", "อุดรธานี"), id="thai-teams",
        ),
        pytest.param(
            ["All staff in York and all staff in Bath saw HTTP 500 on sign-in.",
             "The York office can sign in again. Staff at our Bath office are still blocked by HTTP 500."],
            ("York", "Bath"), id="english-offices",
        ),
    ],
)
def test_audit_scope_followup_tracks_recovery_and_current_impact(messages, expected_scope, run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [Message(when=str(i), text=text) for i, text in enumerate(messages)]
    final = run_audit(ticket, query="HTTP 500", kb_article_ids=["KB-002"], urgency="high",
                      action="escalate_to_human", assigned_team="Incident Response")["result"]

    assert (final["urgency"], final["action"], final["assigned_team"]) == (
        "critical", "escalate_to_human", "Infrastructure / On-call",
    )
    recovered, affected = expected_scope
    assert f"users in {recovered} can access the system again" in final["draft_response"]
    assert f"latest report for {affected} says users could not access" in final["draft_response"]


def test_audit_thai_denied_http_500_keeps_documentation_intent(run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [Message(when="now", text="ทีมเราไม่เจอ HTTP 500 กันเลย ทุกคนเข้าสู่ระบบได้ ขอคู่มือเริ่มต้นครับ")]
    final = run_audit(ticket, query="general documentation guide", kb_article_ids=["KB-004"])["result"]

    assert (final["urgency"], final["action"], final["kb_article_ids"]) == ("low", "auto_respond", ["KB-004"])


def test_audit_thai_team_at_location_escalates_confirmed_impact(run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [Message(when="now", text="พนักงานทั้งทีมที่กระบี่ขึ้น HTTP 500 ตอนล็อกอิน ช่วยดูว่าเฉพาะทีมเราหรือเปล่า?")]
    final = run_audit(ticket, query="HTTP 500", kb_article_ids=["KB-002"])["result"]
    assert (final["urgency"], final["action"], final["assigned_team"]) == (
        "critical", "escalate_to_human", "Infrastructure / On-call",
    )
    assert "regional scope" in final["draft_response"] and "pending confirmation" in final["draft_response"]


def test_audit_recovery_acknowledges_normal_sign_in_after_past_failures(run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [
        Message(when="1", text="All staff in Nagoya were getting HTTP 500."),
        Message(when="2", text="Everyone in Nagoya can sign in normally again."),
    ]
    final = run_audit(ticket, query="HTTP 500", kb_article_ids=["KB-002"])["result"]

    assert "users in Nagoya can access the system again" in final["draft_response"]
    assert "cannot access" not in final["draft_response"]


@pytest.mark.parametrize(
    "text,urgency,single",
    [
        pytest.param(
            "My login throws HTTP 500. Two teammates tested independently and confirmed the identical error.",
            "high", False, id="corroborated-high",
        ),
        pytest.param(
            "My login throws HTTP 500. Two teammates tested independently and confirmed the identical error.",
            "critical", False, id="corroborated-critical",
        ),
        pytest.param("I get HTTP 500 on sign-in.", "high", False, id="scope-unknown"),
        pytest.param(
            "My login throws HTTP 500. I haven't heard back from the rest of the team yet.",
            "high", True, id="one-confirmed-reporter",
        ),
        pytest.param(
            "Only my login returns HTTP 500. My teammates tested separately and can sign in.",
            "high", True, id="other-users-unaffected",
        ),
        pytest.param(
            "My login throws HTTP 500. I hadn't heard back from the team. Two teammates later confirmed the identical error.",
            "high", False, id="later-corroboration",
        ),
    ],
)
def test_audit_access_fallback_requires_evidence_before_downgrading(text, urgency, single, run_audit):
    ticket = ticket_for(PAIRS["P12"], "A")
    ticket.messages = [Message(when="now", text=text)]
    final = run_audit(
        ticket, query="HTTP 500", kb_article_ids=["KB-002"], urgency=urgency,
        action="escalate_to_human", assigned_team="Infrastructure / On-call",
    )["result"]
    actual = (final["urgency"], final["action"], final["assigned_team"])
    if single:
        assert actual == ("medium", "route_to_specialist", "Technical Support")
    else:
        assert actual == (urgency, "escalate_to_human", "Infrastructure / On-call")
        assert "scope" in final["draft_response"].lower()
        assert "unconfirmed" in final["draft_response"].lower()
