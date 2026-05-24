from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from legal_mcp.planner import plan_query
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
