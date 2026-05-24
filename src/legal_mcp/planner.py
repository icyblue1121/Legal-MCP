"""Deterministic query planner for minimum-disclosure tools."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryPlan:
    tool_name: str
    arguments: dict[str, object]
    reason: str


def plan_query(question: str) -> QueryPlan:
    normalized = question.strip()
    if "官网" in normalized or "website" in normalized.lower():
        project = _first_project_like_token(normalized)
        return QueryPlan(
            tool_name="get_project_fields",
            arguments={"project_id_or_name": project, "fields": ["website"]},
            reason="question asks for official website",
        )
    if "总金额" in normalized or "金额" in normalized:
        contract_number = _first_contract_number(normalized)
        return QueryPlan(
            tool_name="get_contract_fields",
            arguments={
                "contract_number": contract_number,
                "fields": ["currency", "total_amount"],
            },
            reason="question asks for contract amount",
        )
    return QueryPlan(
        tool_name="clarify_query",
        arguments={"question": question},
        reason="minimum necessary fields could not be determined",
    )


def _first_project_like_token(question: str) -> str:
    match = re.search(r"[A-Za-z][A-Za-z0-9_-]+", question)
    return match.group(0) if match else question


def _first_contract_number(question: str) -> str:
    match = re.search(r"[A-Z]{2,}[A-Z0-9]*\d{6,}", question)
    return match.group(0) if match else question
