from __future__ import annotations

from legal_mcp.agent_router import (
    build_query_plan_from_question,
    query_plan_from_model_intent,
    route_question,
    validate_agent_decision,
)


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


def test_build_query_plan_for_legal_bp_project_search() -> None:
    plan = build_query_plan_from_question("张三是哪些项目的法务BP？")

    assert plan is not None
    assert plan.domain == "project"
    assert plan.operation == "search"
    assert [(query_filter.field, query_filter.operator, query_filter.value) for query_filter in plan.filters] == [
        ("legal_bp", "eq", "张三")
    ]


def test_build_query_plan_for_contract_counterparty_search() -> None:
    plan = build_query_plan_from_question("哪些合同的相对方包含腾讯？")

    assert plan is not None
    assert plan.domain == "contract"
    assert plan.filters[0].field == "counterparty"
    assert plan.filters[0].operator == "contains"
    assert plan.filters[0].value == "腾讯"


def test_build_query_plan_for_license_actual_operator_search() -> None:
    plan = build_query_plan_from_question("某公司是哪些资质的实际运营方？")

    assert plan is not None
    assert plan.domain == "license"
    assert plan.filters[0].field == "actual_operator"
    assert plan.filters[0].value == "某公司"


def test_build_query_plan_for_cross_domain_search() -> None:
    plan = build_query_plan_from_question("张三关联哪些资料？")

    assert plan is not None
    assert plan.domain == "cross_domain"
    assert plan.filters[0].field == "q"
    assert plan.filters[0].value == "张三"


def test_query_plan_from_model_intent_accepts_valid_catalog_plan() -> None:
    plan = query_plan_from_model_intent(
        {
            "domain": "license",
            "operation": "search",
            "filters": [
                {"field": "project_code", "operator": "eq", "value": "Mgame"},
                {"field": "license_type", "operator": "eq", "value": "trademark_right"},
            ],
            "return_fields": ["license_type", "rights_holder"],
            "limit": 20,
        }
    )

    assert plan is not None
    assert plan.domain == "license"
    assert plan.return_fields == ["license_type", "rights_holder"]


def test_query_plan_from_model_intent_rejects_non_json_shape() -> None:
    plan = query_plan_from_model_intent(
        {
            "domain": "license",
            "operation": "search",
            "filters": "project_code = Mgame",
            "return_fields": ["rights_holder"],
        }
    )

    assert plan is None
