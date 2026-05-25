"""Constrained query plan types for service-side retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_DOMAINS = frozenset({"project", "contract", "license", "cross_domain"})
SUPPORTED_OPERATIONS = frozenset({"lookup", "search", "list", "aggregate"})
SUPPORTED_OPERATORS = frozenset(
    {"eq", "contains", "in", "is_empty", "date_before", "date_after", "date_between"}
)
MAX_LIMIT = 100


@dataclass(frozen=True)
class QueryFilter:
    field: str
    operator: str
    value: Any = None


@dataclass(frozen=True)
class QueryPlan:
    domain: str
    operation: str
    filters: list[QueryFilter]
    return_fields: list[str]
    limit: int = 20


@dataclass(frozen=True)
class PlanValidationResult:
    ok: bool
    error_code: str | None = None
    message: str | None = None


def validate_query_plan(plan: QueryPlan) -> PlanValidationResult:
    if plan.domain not in SUPPORTED_DOMAINS:
        return _invalid("unsupported_domain", "query domain is not supported")
    if plan.operation not in SUPPORTED_OPERATIONS:
        return _invalid("unsupported_operation", "query operation is not supported")
    if not isinstance(plan.limit, int) or plan.limit < 0 or plan.limit > MAX_LIMIT:
        return _invalid("invalid_limit", "query limit must be between 0 and 100")
    if "*" in plan.return_fields:
        return _invalid("wildcard_fields_not_allowed", "return fields must be explicit")
    for field in plan.return_fields:
        if not isinstance(field, str) or not field.strip():
            return _invalid("invalid_return_field", "return fields must be non-empty strings")
    for query_filter in plan.filters:
        if query_filter.operator not in SUPPORTED_OPERATORS:
            return _invalid("unsupported_operator", "query filter operator is not supported")
        if not isinstance(query_filter.field, str) or not query_filter.field.strip():
            return _invalid("invalid_filter_field", "filter fields must be non-empty strings")
    return PlanValidationResult(ok=True)


def _invalid(error_code: str, message: str) -> PlanValidationResult:
    return PlanValidationResult(ok=False, error_code=error_code, message=message)
