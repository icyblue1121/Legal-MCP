from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from legal_mcp.planner import plan_query
from legal_mcp.query_plan import QueryFilter, QueryPlan
from legal_mcp.tool_catalog import agent_capabilities


@dataclass(frozen=True)
class AgentToolDecision:
    tool_name: str
    arguments: dict[str, Any]
    reason: str

    def replace(self, **changes: Any) -> "AgentToolDecision":
        return replace(self, **changes)


def route_question(question: str) -> AgentToolDecision:
    plan = plan_query(question)
    arguments = dict(plan.arguments)
    arguments.setdefault("rationale", f"agent_query: {plan.reason}")
    arguments.setdefault("source_client", "legal-mcp-agent")
    return AgentToolDecision(
        tool_name=plan.tool_name,
        arguments=arguments,
        reason=plan.reason,
    )


def _project_scoped_license_plan(
    project: str,
    *,
    license_type: str,
    return_fields: list[str],
) -> QueryPlan:
    return QueryPlan(
        domain="license",
        operation="search",
        filters=[
            QueryFilter(field="project_code", operator="eq", value=project),
            QueryFilter(field="license_type", operator="eq", value=license_type),
        ],
        return_fields=["license_type", *return_fields],
        limit=20,
    )


def build_query_plan_from_question(question: str) -> QueryPlan | None:
    normalized = question.strip().replace(" ", "")
    if not normalized or "所有项目资料" in normalized:
        return None

    match = re.search(r"(.+?)的商标(?:在哪家公司|权利人是谁|权利人是什么)[？?]?$", normalized, re.IGNORECASE)
    if match:
        return _project_scoped_license_plan(
            match.group(1),
            license_type="trademark_right",
            return_fields=["rights_holder"],
        )

    match = re.search(r"(.+?)是哪些项目的法务BP", normalized, re.IGNORECASE)
    if match:
        return QueryPlan(
            domain="project",
            operation="search",
            filters=[QueryFilter(field="legal_bp", operator="eq", value=match.group(1))],
            return_fields=["project_code", "name"],
            limit=50,
        )

    match = re.search(r"哪些合同.*相对方包含(.+?)[？?]?$", normalized)
    if match:
        return QueryPlan(
            domain="contract",
            operation="search",
            filters=[
                QueryFilter(field="counterparty", operator="contains", value=match.group(1))
            ],
            return_fields=["contract_number", "title", "counterparty"],
            limit=50,
        )

    match = re.search(r"(.+?)是哪些资质的实际运营方", normalized)
    if match:
        return QueryPlan(
            domain="license",
            operation="search",
            filters=[
                QueryFilter(field="actual_operator", operator="eq", value=match.group(1))
            ],
            return_fields=["license_type", "actual_operator"],
            limit=50,
        )

    match = re.search(r"(.+?)关联哪些资料", normalized)
    if match:
        return QueryPlan(
            domain="cross_domain",
            operation="search",
            filters=[QueryFilter(field="q", operator="contains", value=match.group(1))],
            return_fields=[
                "project_code",
                "name",
                "contract_number",
                "title",
                "license_type",
                "actual_operator",
            ],
            limit=50,
        )

    match = re.search(r"(.+?)的官网是什么", normalized)
    if match:
        return QueryPlan(
            domain="project",
            operation="lookup",
            filters=[QueryFilter(field="project_code", operator="eq", value=match.group(1))],
            return_fields=["project_code", "name", "website"],
            limit=1,
        )

    return None


def query_plan_from_model_intent(intent: dict[str, Any]) -> QueryPlan | None:
    domain = intent.get("domain")
    operation = intent.get("operation")
    raw_filters = intent.get("filters")
    raw_return_fields = intent.get("return_fields")
    raw_limit = intent.get("limit", 20)
    if not isinstance(domain, str) or not isinstance(operation, str):
        return None
    if not isinstance(raw_filters, list) or not isinstance(raw_return_fields, list):
        return None
    if not all(isinstance(field, str) for field in raw_return_fields):
        return None
    limit = raw_limit if isinstance(raw_limit, int) else 20
    filters: list[QueryFilter] = []
    for raw_filter in raw_filters:
        if not isinstance(raw_filter, dict):
            return None
        field = raw_filter.get("field")
        operator = raw_filter.get("operator")
        if not isinstance(field, str) or not isinstance(operator, str):
            return None
        filters.append(QueryFilter(field=field, operator=operator, value=raw_filter.get("value")))
    return QueryPlan(
        domain=domain,
        operation=operation,
        filters=filters,
        return_fields=raw_return_fields,
        limit=limit,
    )


def validate_agent_decision(decision: AgentToolDecision) -> dict[str, Any]:
    allowed = {capability.name: capability for capability in agent_capabilities()}
    capability = allowed.get(decision.tool_name)
    if capability is None:
        return _agent_error(
            "agent_tool_not_allowed",
            "agent selected a tool outside its read capability boundary",
        )

    fields = decision.arguments.get("fields")
    if fields is not None:
        if not isinstance(fields, list) or not all(isinstance(field, str) for field in fields):
            return _agent_error("agent_field_not_allowed", "fields must be a list of strings")
        unknown_fields = sorted(set(fields) - set(capability.return_fields))
        if unknown_fields:
            return _agent_error(
                "agent_field_not_allowed",
                "agent selected fields outside the tool capability",
                details={"fields": unknown_fields},
            )

    if capability.requires_fields and "fields" not in decision.arguments:
        return _agent_error("agent_fields_required", "agent must request explicit fields")

    return {"ok": True}


def clarify_result(question: str) -> dict[str, Any]:
    return {
        "clarification": {
            "question": question,
            "message": "请明确项目、合同、证照或字段范围，以便按最小披露原则查询。",
        }
    }


def _agent_error(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}
