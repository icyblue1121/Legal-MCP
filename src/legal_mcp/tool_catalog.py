"""Machine-readable MCP tool catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PROJECT_FIELDS = (
    "project_code",
    "name",
    "stage",
    "legal_bp",
    "department",
    "release_team",
    "contact_person",
    "website",
    "notes",
)

CONTRACT_FIELDS = (
    "contract_number",
    "title",
    "counterparty",
    "company_entity",
    "currency",
    "total_amount",
    "signed_date",
    "expiry_date",
    "payment_terms",
    "handler",
    "income_expense_type",
    "summary",
)

LICENSE_FIELDS = (
    "license_type",
    "identifier",
    "entity_name",
    "issuer",
    "approval_number",
    "rights_holder",
    "copyright_holder",
    "operating_entity",
    "actual_operator",
    "authorization_relation",
    "expiry_date",
    "notes",
)


@dataclass(frozen=True)
class ToolCapability:
    name: str
    description: str
    data_domain: str
    operation: str
    filters: tuple[str, ...]
    return_fields: tuple[str, ...]
    requires_project_scope: bool
    result_kind: str
    default_limit: int | None = None
    max_limit: int | None = None


CATALOG: dict[str, ToolCapability] = {
    "plan_query": ToolCapability(
        name="plan_query",
        description="Plan a user question into one minimum-disclosure tool call.",
        data_domain="planner",
        operation="read",
        filters=("question",),
        return_fields=("tool_name", "arguments", "reason"),
        requires_project_scope=False,
        result_kind="single",
    ),
    "resolve_project": ToolCapability(
        name="resolve_project",
        description=(
            "Resolve a project by code, name, or alias. Do not use for user "
            "permissions; use describe_my_access for permission questions."
        ),
        data_domain="project",
        operation="read",
        filters=("query",),
        return_fields=("project_code", "name"),
        requires_project_scope=False,
        result_kind="single_or_candidates",
    ),
    "describe_my_access": ToolCapability(
        name="describe_my_access",
        description=(
            "Query the current user's permissions: visible projects, accessible "
            "project codes, and fields the user can read."
        ),
        data_domain="access",
        operation="read",
        filters=(),
        return_fields=("projects", "fields"),
        requires_project_scope=False,
        result_kind="list",
    ),
    "get_project_fields": ToolCapability(
        name="get_project_fields",
        description="Return selected project fields after field-level authorization.",
        data_domain="project",
        operation="read",
        filters=("project_id_or_name", "fields"),
        return_fields=PROJECT_FIELDS,
        requires_project_scope=True,
        result_kind="single",
    ),
    "list_project_contracts": ToolCapability(
        name="list_project_contracts",
        description="List contracts for a project with selected contract fields.",
        data_domain="contract",
        operation="read",
        filters=("project_id_or_name", "fields", "limit"),
        return_fields=CONTRACT_FIELDS,
        requires_project_scope=True,
        result_kind="list",
        default_limit=20,
        max_limit=100,
    ),
    "list_project_licenses": ToolCapability(
        name="list_project_licenses",
        description="List licenses for a project with selected license fields.",
        data_domain="license",
        operation="read",
        filters=("project_id_or_name", "fields", "limit"),
        return_fields=LICENSE_FIELDS,
        requires_project_scope=True,
        result_kind="list",
        default_limit=20,
        max_limit=100,
    ),
    "get_contract_fields": ToolCapability(
        name="get_contract_fields",
        description="Return selected fields for one contract.",
        data_domain="contract",
        operation="read",
        filters=("contract_number", "fields"),
        return_fields=CONTRACT_FIELDS,
        requires_project_scope=True,
        result_kind="single",
    ),
}


def tool_definitions() -> list[dict[str, Any]]:
    return [_tool_definition(capability) for capability in CATALOG.values()]


def _tool_definition(capability: ToolCapability) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "rationale": {"type": "string"},
        "source_client": {"type": "string"},
    }
    required = ["rationale"]
    for filter_name in capability.filters:
        if filter_name == "fields":
            properties["fields"] = {
                "type": "array",
                "items": {"type": "string", "enum": sorted(capability.return_fields)},
            }
            required.append("fields")
        elif filter_name == "limit":
            properties["limit"] = {
                "type": "integer",
                "default": capability.default_limit,
                "maximum": capability.max_limit,
            }
        else:
            properties[filter_name] = {"type": "string"}
            required.append(filter_name)
    return {
        "name": capability.name,
        "description": capability.description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
        "x-legal-mcp": {
            "data_domain": capability.data_domain,
            "operation": capability.operation,
            "filters": list(capability.filters),
            "return_fields": list(capability.return_fields),
            "requires_project_scope": capability.requires_project_scope,
            "result_kind": capability.result_kind,
            "default_limit": capability.default_limit,
            "max_limit": capability.max_limit,
        },
    }
