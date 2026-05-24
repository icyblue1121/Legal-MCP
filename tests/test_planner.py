from __future__ import annotations

from legal_mcp.planner import plan_query


def test_planner_maps_website_question_to_project_fields() -> None:
    plan = plan_query("MGAME 的官网是什么？")

    assert plan.tool_name == "get_project_fields"
    assert plan.arguments["project_id_or_name"] == "MGAME"
    assert plan.arguments["fields"] == ["website"]


def test_planner_maps_contract_amount_question_to_contract_fields() -> None:
    plan = plan_query("合同 SHYBYBZ2025000082 的总金额是多少？")

    assert plan.tool_name == "get_contract_fields"
    assert plan.arguments["contract_number"] == "SHYBYBZ2025000082"
    assert plan.arguments["fields"] == ["currency", "total_amount"]
