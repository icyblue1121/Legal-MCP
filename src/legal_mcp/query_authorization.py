"""Authorization checks for constrained query plans."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from legal_mcp.disclosure_audit import Disclosure
from legal_mcp.policy import AccessContext, authorize_fields, visible_project_ids
from legal_mcp.query_plan import QueryPlan, validate_query_plan

PROJECT_IDENTITY_FIELDS = frozenset({"project_code", "name"})
CONTRACT_IDENTITY_FIELDS = frozenset({"contract_number", "title"})
LICENSE_IDENTITY_FIELDS = frozenset({"license_type", "identifier"})


@dataclass(frozen=True)
class AuthorizedQueryPlan:
    plan: QueryPlan


@dataclass(frozen=True)
class QueryAuthorizationResult:
    ok: bool
    authorized_plan: AuthorizedQueryPlan | None = None
    error_code: str | None = None
    message: str | None = None
    disclosures: list[Disclosure] = field(default_factory=list)


def authorize_query_plan(
    conn: sqlite3.Connection,
    plan: QueryPlan,
    access_context: AccessContext | None,
) -> QueryAuthorizationResult:
    validation = validate_query_plan(plan)
    if not validation.ok:
        return QueryAuthorizationResult(
            ok=False,
            error_code=validation.error_code,
            message=validation.message,
        )

    if plan.domain == "cross_domain":
        return _authorize_cross_domain(conn, plan, access_context)

    identity_fields = _identity_fields(plan.domain)
    filter_fields = {query_filter.field for query_filter in plan.filters} - identity_fields
    return_fields = set(plan.return_fields) - identity_fields
    project_ids = _authorization_project_ids(conn, access_context)

    filter_denials = _denials_for_fields(
        conn,
        access_context,
        data_domain=plan.domain,
        project_ids=project_ids,
        fields=filter_fields,
        record_type=plan.domain,
    )
    if filter_denials:
        return QueryAuthorizationResult(
            ok=False,
            error_code="filter_field_access_denied",
            message="one or more filter fields are not granted",
            disclosures=filter_denials,
        )

    return_denials = _denials_for_fields(
        conn,
        access_context,
        data_domain=plan.domain,
        project_ids=project_ids,
        fields=return_fields,
        record_type=plan.domain,
    )
    if return_denials:
        return QueryAuthorizationResult(
            ok=False,
            error_code="return_field_access_denied",
            message="one or more return fields are not granted",
            disclosures=return_denials,
        )

    return QueryAuthorizationResult(ok=True, authorized_plan=AuthorizedQueryPlan(plan))


def _authorize_cross_domain(
    conn: sqlite3.Connection,
    plan: QueryPlan,
    access_context: AccessContext | None,
) -> QueryAuthorizationResult:
    project_ids = _authorization_project_ids(conn, access_context)
    checks = {
        "project": {"legal_bp", "name"} - PROJECT_IDENTITY_FIELDS,
        "contract": {"counterparty", "handler", "title"} - CONTRACT_IDENTITY_FIELDS,
        "license": {"actual_operator", "operating_entity", "license_type"}
        - LICENSE_IDENTITY_FIELDS,
    }
    disclosures: list[Disclosure] = []
    for domain, fields in checks.items():
        disclosures.extend(
            _denials_for_fields(
                conn,
                access_context,
                data_domain=domain,
                project_ids=project_ids,
                fields=fields,
                record_type=domain,
            )
        )
    if disclosures:
        return QueryAuthorizationResult(
            ok=False,
            error_code="filter_field_access_denied",
            message="one or more cross-domain search fields are not granted",
            disclosures=disclosures,
        )
    return QueryAuthorizationResult(ok=True, authorized_plan=AuthorizedQueryPlan(plan))


def _authorization_project_ids(
    conn: sqlite3.Connection,
    access_context: AccessContext | None,
) -> set[int | None]:
    visible = visible_project_ids(conn, access_context)
    if visible is None:
        return {None}
    return set(visible)


def _denials_for_fields(
    conn: sqlite3.Connection,
    access_context: AccessContext | None,
    *,
    data_domain: str,
    project_ids: set[int | None],
    fields: set[str],
    record_type: str,
) -> list[Disclosure]:
    if not fields:
        return []

    disclosures: list[Disclosure] = []
    for project_id in sorted(project_ids, key=lambda value: -1 if value is None else value):
        decision = authorize_fields(
            conn,
            access_context,
            operation="read",
            data_domain=data_domain,
            project_id=project_id,
            requested_fields=fields,
        )
        for field_name, reason in sorted(decision.denied_fields.items()):
            disclosures.append(
                Disclosure(
                    project_id=project_id,
                    record_type=record_type,
                    record_id=None,
                    field_name=field_name,
                    decision="denied",
                    reason=reason,
                )
            )
    return disclosures


def _identity_fields(domain: str) -> frozenset[str]:
    if domain == "project":
        return PROJECT_IDENTITY_FIELDS
    if domain == "contract":
        return CONTRACT_IDENTITY_FIELDS
    if domain == "license":
        return LICENSE_IDENTITY_FIELDS
    return frozenset()
