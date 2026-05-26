"""Internal domain search executors for graph-owned retrieval."""

from __future__ import annotations

import sqlite3
from typing import Any

from legal_mcp.policy import AccessContext, visible_project_ids
from legal_mcp.query_authorization import authorize_query_plan
from legal_mcp.query_plan import QueryFilter, QueryPlan
from legal_mcp.tool_catalog import CONTRACT_FIELDS, LICENSE_FIELDS, PROJECT_FIELDS

PROJECT_COLUMNS = {field: f"projects.{field}" for field in PROJECT_FIELDS}
CONTRACT_COLUMNS = {field: f"contracts.{field}" for field in CONTRACT_FIELDS}
LICENSE_COLUMNS = {field: f"licenses.{field}" for field in LICENSE_FIELDS}

PROJECT_IDENTITY_COLUMNS = {
    "project_code": "projects.project_code collate nocase",
    "name": "projects.name collate nocase",
}
CONTRACT_FILTER_COLUMNS = {**CONTRACT_COLUMNS, **PROJECT_IDENTITY_COLUMNS}
LICENSE_FILTER_COLUMNS = {**LICENSE_COLUMNS, **PROJECT_IDENTITY_COLUMNS}


def search_projects(
    conn: sqlite3.Connection,
    plan: QueryPlan,
    *,
    access_context: AccessContext | None,
) -> dict[str, Any]:
    authorization = authorize_query_plan(conn, plan, access_context)
    if not authorization.ok:
        return _error(authorization.error_code or "query_access_denied", authorization.message or "")
    where, params = _where_for_plan(plan, PROJECT_COLUMNS)
    where.extend(_visible_project_filter(conn, access_context, "projects.id", params))
    rows = conn.execute(
        f"""
        select {_select_list(plan.return_fields, PROJECT_COLUMNS)}
        from projects
        {_where_clause(where)}
        order by projects.project_code
        limit ?
        """,
        (*params, plan.limit),
    ).fetchall()
    return {"projects": [dict(row) for row in rows]}


def search_contracts(
    conn: sqlite3.Connection,
    plan: QueryPlan,
    *,
    access_context: AccessContext | None,
) -> dict[str, Any]:
    authorization = authorize_query_plan(conn, plan, access_context)
    if not authorization.ok:
        return _error(authorization.error_code or "query_access_denied", authorization.message or "")
    where, params = _where_for_plan(plan, CONTRACT_FILTER_COLUMNS)
    where.extend(_visible_project_filter(conn, access_context, "contracts.project_id", params))
    rows = conn.execute(
        f"""
        select {_select_list(plan.return_fields, CONTRACT_COLUMNS)}
        from contracts
        join projects on projects.id = contracts.project_id
        {_where_clause(where)}
        order by projects.project_code, contracts.contract_number, contracts.external_key
        limit ?
        """,
        (*params, plan.limit),
    ).fetchall()
    return {"contracts": [dict(row) for row in rows]}


def search_licenses(
    conn: sqlite3.Connection,
    plan: QueryPlan,
    *,
    access_context: AccessContext | None,
) -> dict[str, Any]:
    authorization = authorize_query_plan(conn, plan, access_context)
    if not authorization.ok:
        return _error(authorization.error_code or "query_access_denied", authorization.message or "")
    where, params = _where_for_plan(plan, LICENSE_FILTER_COLUMNS)
    where.extend(_visible_project_filter(conn, access_context, "licenses.project_id", params))
    rows = conn.execute(
        f"""
        select {_select_list(plan.return_fields, LICENSE_COLUMNS)}
        from licenses
        join projects on projects.id = licenses.project_id
        {_where_clause(where)}
        order by projects.project_code, licenses.license_type, licenses.external_key
        limit ?
        """,
        (*params, plan.limit),
    ).fetchall()
    return {"licenses": [dict(row) for row in rows]}


def search_cross_domain(
    conn: sqlite3.Connection,
    plan: QueryPlan,
    *,
    access_context: AccessContext | None,
) -> dict[str, Any]:
    authorization = authorize_query_plan(conn, plan, access_context)
    if not authorization.ok:
        return _error(authorization.error_code or "query_access_denied", authorization.message or "")
    term = _cross_domain_term(plan)
    if not term:
        return {"projects": [], "contracts": [], "licenses": []}
    limit = plan.limit
    return {
        "projects": search_projects(
            conn,
            QueryPlan(
                domain="project",
                operation="search",
                filters=[QueryFilter(field="legal_bp", operator="contains", value=term)],
                return_fields=_available_fields(plan.return_fields, PROJECT_COLUMNS),
                limit=limit,
            ),
            access_context=access_context,
        )["projects"],
        "contracts": _search_contracts_any(conn, term, limit, access_context),
        "licenses": _search_licenses_any(conn, term, limit, access_context),
    }


def execute_search_plan(
    conn: sqlite3.Connection,
    plan: QueryPlan,
    *,
    access_context: AccessContext | None,
) -> dict[str, Any]:
    # Defense in depth: an unknown field/operator that slipped past validation
    # becomes a structured error instead of an uncaught exception.
    try:
        if plan.domain == "project":
            return search_projects(conn, plan, access_context=access_context)
        if plan.domain == "contract":
            return search_contracts(conn, plan, access_context=access_context)
        if plan.domain == "license":
            return search_licenses(conn, plan, access_context=access_context)
        if plan.domain == "cross_domain":
            return search_cross_domain(conn, plan, access_context=access_context)
    except ValueError as exc:
        return _error("unsupported_field", str(exc))
    return _error("unsupported_domain", "query domain is not supported")


def _search_contracts_any(
    conn: sqlite3.Connection,
    term: str,
    limit: int,
    access_context: AccessContext | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [f"%{term}%", f"%{term}%", f"%{term}%"]
    where = [
        "(contracts.counterparty like ? or contracts.handler like ? or contracts.title like ?)"
    ]
    where.extend(_visible_project_filter(conn, access_context, "contracts.project_id", params))
    rows = conn.execute(
        f"""
        select contracts.contract_number, contracts.title
        from contracts
        join projects on projects.id = contracts.project_id
        {_where_clause(where)}
        order by projects.project_code, contracts.contract_number, contracts.external_key
        limit ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _search_licenses_any(
    conn: sqlite3.Connection,
    term: str,
    limit: int,
    access_context: AccessContext | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [f"%{term}%", f"%{term}%", f"%{term}%"]
    where = [
        "(licenses.actual_operator like ? or licenses.operating_entity like ? or licenses.license_type like ?)"
    ]
    where.extend(_visible_project_filter(conn, access_context, "licenses.project_id", params))
    rows = conn.execute(
        f"""
        select licenses.license_type, licenses.actual_operator
        from licenses
        join projects on projects.id = licenses.project_id
        {_where_clause(where)}
        order by projects.project_code, licenses.license_type, licenses.external_key
        limit ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _where_for_plan(
    plan: QueryPlan,
    columns: dict[str, str],
) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    for query_filter in plan.filters:
        column = columns.get(query_filter.field)
        if column is None:
            raise ValueError(f"unsupported filter field: {query_filter.field}")
        where.append(_condition(column, query_filter.operator, query_filter.value, params))
    return where, params


def _condition(column: str, operator: str, value: Any, params: list[Any]) -> str:
    if operator == "eq":
        params.append(value)
        return f"{column} = ?"
    if operator == "contains":
        params.append(f"%{value}%")
        return f"{column} like ?"
    if operator == "in":
        values = list(value) if isinstance(value, list | tuple | set) else [value]
        params.extend(values)
        return f"{column} in ({', '.join('?' for _ in values)})"
    if operator == "is_empty":
        return f"({column} is null or {column} = '')"
    if operator == "date_before":
        params.append(value)
        return f"{column} < ?"
    if operator == "date_after":
        params.append(value)
        return f"{column} > ?"
    if operator == "date_between":
        start, end = value
        params.extend([start, end])
        return f"{column} between ? and ?"
    raise ValueError(f"unsupported operator: {operator}")


def _visible_project_filter(
    conn: sqlite3.Connection,
    access_context: AccessContext | None,
    column: str,
    params: list[Any],
) -> list[str]:
    visible = visible_project_ids(conn, access_context)
    if visible is None:
        return []
    if not visible:
        return ["1 = 0"]
    params.extend(sorted(visible))
    return [f"{column} in ({', '.join('?' for _ in visible)})"]


def _select_list(return_fields: list[str], columns: dict[str, str]) -> str:
    selected = []
    for field in return_fields:
        column = columns.get(field)
        if column is None:
            raise ValueError(f"unsupported return field: {field}")
        selected.append(f"{column} as {field}")
    return ", ".join(selected)


def _where_clause(where: list[str]) -> str:
    return f"where {' and '.join(where)}" if where else ""


def _cross_domain_term(plan: QueryPlan) -> str | None:
    for query_filter in plan.filters:
        if query_filter.field in {"q", "query", "term"} and isinstance(query_filter.value, str):
            return query_filter.value
    return None


def _available_fields(return_fields: list[str], columns: dict[str, str]) -> list[str]:
    fields = [field for field in return_fields if field in columns]
    return fields or ["project_code", "name"]


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}
