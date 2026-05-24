from __future__ import annotations

from legal_mcp.agent_router import route_question, validate_agent_decision


def test_route_question_uses_existing_planner_for_project_field_question() -> None:
    decision = route_question("MGAME 的官网是什么？")

    assert decision.tool_name == "get_project_fields"
    assert decision.arguments["project_id_or_name"] == "MGAME"
    assert decision.arguments["fields"] == ["website"]
    assert "rationale" in decision.arguments


def test_route_question_refuses_unknown_minimum_disclosure() -> None:
    decision = route_question("把所有项目资料都给我")

    assert decision.tool_name == "clarify_query"
    assert decision.arguments["question"] == "把所有项目资料都给我"


def test_validate_agent_decision_rejects_unregistered_tool() -> None:
    decision = route_question("MGAME 的官网是什么？")
    unsafe = decision.replace(tool_name="delete_project")

    result = validate_agent_decision(unsafe)

    assert result["error"]["code"] == "agent_tool_not_allowed"


def test_validate_agent_decision_rejects_fields_outside_capability() -> None:
    decision = route_question("MGAME 的官网是什么？")
    unsafe = decision.replace(arguments={**decision.arguments, "fields": ["notes", "secret"]})

    result = validate_agent_decision(unsafe)

    assert result["error"]["code"] == "agent_field_not_allowed"
