"""MCP tool definitions and execution."""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from legal_mcp import db
from legal_mcp.audit import DEFAULT_AUDIT_PATH, write_audit_record
from legal_mcp.disclosure_audit import Disclosure, write_audit_event
from legal_mcp.lookup import ProjectLookupResult, lookup_project
from legal_mcp.policy import (
    AccessContext,
    can_query_content,
    project_is_visible,
    visible_project_ids,
)
from legal_mcp.tools_project import get_project_fields, resolve_project

PROJECT_FIELD_NAMES = {
    "project_code",
    "name",
    "stage",
    "legal_bp",
    "department",
    "release_team",
    "contact_person",
    "website",
    "notes",
}
PROJECT_FIELD_IDENTITY_NAMES = ("project_code", "name")


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_projects",
        "description": "List legal projects, optionally filtered by stage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string"},
                "rationale": {"type": "string"},
                "source_client": {"type": "string"},
            },
            "required": ["rationale"],
        },
    },
    {
        "name": "get_project_context",
        "description": "Return a project and related legal context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id_or_name": {"type": "string"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(PROJECT_FIELD_NAMES)},
                },
                "rationale": {"type": "string"},
                "source_client": {"type": "string"},
            },
            "required": ["project_id_or_name", "rationale"],
        },
    },
    {
        "name": "list_expiring_licenses",
        "description": "List licenses expiring within a day boundary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "default": 30},
                "rationale": {"type": "string"},
                "source_client": {"type": "string"},
            },
            "required": ["rationale"],
        },
    },
    {
        "name": "list_open_risks",
        "description": "List open risks, optionally filtered by project code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_code": {"type": "string"},
                "rationale": {"type": "string"},
                "source_client": {"type": "string"},
            },
            "required": ["rationale"],
        },
    },
]


def call_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    database_path: str | Path,
    audit_path: str | Path = DEFAULT_AUDIT_PATH,
    access_context: AccessContext | None = None,
) -> dict[str, Any]:
    rationale = arguments.get("rationale")
    source_client = arguments.get("source_client")
    if not isinstance(rationale, str) or not rationale.strip():
        result = _error("missing_rationale", "rationale is required")
        _audit(tool_name, rationale, source_client, arguments, result, audit_path)
        _audit_database(
            database_path,
            access_context,
            tool_name,
            rationale,
            source_client,
            arguments,
            result,
            [],
        )
        return result

    if not can_query_content(access_context):
        result = _error("access_denied", "user is not allowed to query project content")
        _audit(tool_name, rationale, source_client, arguments, result, audit_path)
        _audit_database(
            database_path,
            access_context,
            tool_name,
            rationale,
            source_client,
            arguments,
            result,
            [],
        )
        return result

    disclosures: list[Disclosure] = []
    try:
        conn = db.connect(database_path)
        try:
            if tool_name == "list_projects":
                result = _list_projects(conn, arguments, access_context)
            elif tool_name == "resolve_project":
                result = resolve_project(conn, arguments, access_context)
            elif tool_name == "get_project_fields":
                result = get_project_fields(conn, arguments, access_context)
            elif tool_name == "get_project_context":
                result = _error(
                    "deprecated_tool",
                    "get_project_context is deprecated; use fine-grained field tools",
                )
            elif tool_name == "list_expiring_licenses":
                result = _list_expiring_licenses(conn, arguments, access_context)
            elif tool_name == "list_open_risks":
                result = _list_open_risks(conn, arguments, access_context, disclosures)
            else:
                result = _error("validation_error", f"unknown tool: {tool_name}")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        result = _error("database_error", "database operation failed", details={"reason": str(exc)})

    disclosures.extend(_disclosures_from_result(result))
    _audit(tool_name, rationale, source_client, arguments, result, audit_path)
    _audit_database(
        database_path,
        access_context,
        tool_name,
        rationale,
        source_client,
        arguments,
        result,
        disclosures,
    )
    return result


def _list_projects(
    conn: sqlite3.Connection,
    arguments: dict[str, Any],
    access_context: AccessContext | None,
) -> dict[str, Any]:
    stage = arguments.get("stage")
    visible = visible_project_ids(conn, access_context)
    if visible == set():
        return {"projects": []}

    filters: list[str] = []
    params: list[Any] = []
    if stage:
        filters.append("stage = ?")
        params.append(stage)
    if visible is not None:
        placeholders = ", ".join("?" for _ in visible)
        filters.append(f"id in ({placeholders})")
        params.extend(sorted(visible))

    where = f" where {' and '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"select * from projects{where} order by project_code",
        params,
    ).fetchall()
    return {"projects": [dict(row) for row in rows]}


def _get_project_context(
    conn: sqlite3.Connection,
    arguments: dict[str, Any],
    access_context: AccessContext | None,
    disclosures: list[Disclosure],
) -> dict[str, Any]:
    query = arguments.get("project_id_or_name")
    if not isinstance(query, str) or not query.strip():
        return _error("validation_error", "project_id_or_name is required")
    fields = _requested_project_fields(arguments)
    if fields == set():
        return _error("validation_error", "fields must contain known project field names")

    lookup = lookup_project(conn, query)
    if lookup.kind == ProjectLookupResult.NOT_FOUND:
        return _error("not_found", "project not found")
    if lookup.kind == ProjectLookupResult.AMBIGUOUS:
        visible = visible_project_ids(conn, access_context)
        if visible is None:
            return _error(
                "ambiguous_project",
                "project lookup is ambiguous",
                candidates=lookup.candidates or [],
            )

        disclosures.extend(
            Disclosure(
                project_id=int(candidate["id"]),
                record_type="project",
                record_id=int(candidate["id"]),
                decision="denied",
                reason="project_hidden",
            )
            for candidate in lookup.candidates or []
            if int(candidate["id"]) not in visible
        )
        visible_candidates = [
            candidate
            for candidate in lookup.candidates or []
            if int(candidate["id"]) in visible
        ]
        if not visible_candidates:
            return _error("not_found", "project not found")
        if len(visible_candidates) == 1:
            row = conn.execute(
                "select * from projects where id = ?",
                (visible_candidates[0]["id"],),
            ).fetchone()
            if row is None:
                return _error("not_found", "project not found")
            return _project_context(conn, dict(row), fields)
        return _error(
            "ambiguous_project",
            "project lookup is ambiguous",
            candidates=visible_candidates,
        )

    project = lookup.project or {}
    project_id = project["id"]
    if not project_is_visible(conn, access_context, int(project_id)):
        disclosures.append(
            Disclosure(
                project_id=int(project_id),
                record_type="project",
                record_id=int(project_id),
                decision="denied",
                reason="project_hidden",
            )
        )
        return _error("not_found", "project not found")

    return _project_context(conn, project, fields)


def _requested_project_fields(arguments: dict[str, Any]) -> set[str] | None:
    fields = arguments.get("fields")
    if fields is None:
        return None
    if not isinstance(fields, list):
        return set()
    requested = {field for field in fields if isinstance(field, str)}
    if len(requested) != len(fields) or not requested.issubset(PROJECT_FIELD_NAMES):
        return set()
    return requested


def _project_context(
    conn: sqlite3.Connection,
    project: dict[str, Any],
    fields: set[str] | None = None,
) -> dict[str, Any]:
    if fields is not None:
        projected_fields = [*PROJECT_FIELD_IDENTITY_NAMES, *sorted(fields)]
        return {
            "project": {
                field: project.get(field)
                for field in projected_fields
                if field in project
            }
        }

    project_id = project["id"]
    licenses = conn.execute(
        "select * from licenses where project_id = ? order by external_key",
        (project_id,),
    ).fetchall()
    contracts = conn.execute(
        "select * from contracts where project_id = ? order by external_key",
        (project_id,),
    ).fetchall()
    risks = conn.execute(
        "select * from risks where project_id = ? order by external_key",
        (project_id,),
    ).fetchall()
    return {
        "project": project,
        "licenses": [dict(row) for row in licenses],
        "contracts": [dict(row) for row in contracts],
        "risks": [dict(row) for row in risks],
    }


def _list_expiring_licenses(
    conn: sqlite3.Connection,
    arguments: dict[str, Any],
    access_context: AccessContext | None,
) -> dict[str, Any]:
    days_ahead = arguments.get("days_ahead", 30)
    if not isinstance(days_ahead, int) or days_ahead < 0:
        return _error("validation_error", "days_ahead must be a non-negative integer")
    visible = visible_project_ids(conn, access_context)
    if visible == set():
        return {"licenses": []}

    start = date.today().isoformat()
    end = (date.today() + timedelta(days=days_ahead)).isoformat()
    project_filter = ""
    params: list[Any] = [start, end]
    if visible is not None:
        placeholders = ", ".join("?" for _ in visible)
        project_filter = f" and projects.id in ({placeholders})"
        params.extend(sorted(visible))

    rows = conn.execute(
        f"""
        select licenses.*, projects.project_code, projects.name as project_name
        from licenses
        join projects on projects.id = licenses.project_id
        where licenses.expiry_date is not null
          and licenses.expiry_date >= ?
          and licenses.expiry_date <= ?
          {project_filter}
        order by licenses.expiry_date, projects.project_code, licenses.external_key
        """,
        params,
    ).fetchall()
    return {"licenses": [dict(row) for row in rows]}


def _list_open_risks(
    conn: sqlite3.Connection,
    arguments: dict[str, Any],
    access_context: AccessContext | None,
    disclosures: list[Disclosure],
) -> dict[str, Any]:
    project_code = arguments.get("project_code")
    visible = visible_project_ids(conn, access_context)
    if isinstance(project_code, str) and project_code.strip() and visible is not None:
        project = conn.execute(
            "select id from projects where project_code = ?",
            (project_code,),
        ).fetchone()
        if project is not None and int(project["id"]) not in visible:
            disclosures.append(
                Disclosure(
                    project_id=int(project["id"]),
                    record_type="project",
                    record_id=int(project["id"]),
                    decision="denied",
                    reason="project_hidden",
                )
            )
            return {"risks": []}

    if visible == set():
        return {"risks": []}

    filters = ["risks.status = 'open'"]
    params: list[Any] = []
    if project_code:
        filters.append("projects.project_code = ?")
        params.append(project_code)
    if visible is not None:
        placeholders = ", ".join("?" for _ in visible)
        filters.append(f"projects.id in ({placeholders})")
        params.extend(sorted(visible))

    rows = conn.execute(
        f"""
        select risks.*, projects.project_code, projects.name as project_name
        from risks
        join projects on projects.id = risks.project_id
        where {' and '.join(filters)}
        order by projects.project_code, risks.external_key
        """,
        params,
    ).fetchall()
    return {"risks": [dict(row) for row in rows]}


def _error(
    code: str,
    message: str,
    *,
    candidates: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "candidates": candidates or [],
            "details": details or {},
        }
    }


def _audit(
    tool_name: str,
    rationale: str | None,
    source_client: str | None,
    arguments: dict[str, Any],
    result: dict[str, Any],
    audit_path: str | Path,
) -> None:
    error = result.get("error")
    write_audit_record(
        tool_name=tool_name,
        rationale=rationale,
        source_client=source_client,
        arguments=arguments,
        result_status="error" if error else "success",
        error_code=error["code"] if error else None,
        audit_path=audit_path,
    )


def _audit_database(
    database_path: str | Path,
    access_context: AccessContext | None,
    tool_name: str,
    rationale: str | None,
    source_client: str | None,
    arguments: dict[str, Any],
    result: dict[str, Any],
    disclosures: list[Disclosure],
) -> None:
    try:
        conn = db.connect(database_path)
        try:
            write_audit_event(
                conn,
                context=access_context,
                tool_name=tool_name,
                rationale=rationale,
                source_client=source_client,
                arguments=arguments,
                result=result,
                disclosures=disclosures,
            )
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"legal-mcp: database audit write failed: {exc}", file=sys.stderr)
        return


def _disclosures_from_result(result: dict[str, Any]) -> list[Disclosure]:
    error = result.get("error")
    if error:
        if not isinstance(error, dict) or error.get("code") != "ambiguous_project":
            return []

        disclosures: list[Disclosure] = []
        for candidate in error.get("candidates", []):
            if isinstance(candidate, dict):
                disclosure = _disclosure_from_record(candidate, "project", candidate)
                if disclosure is not None:
                    disclosures.append(disclosure)
        return disclosures

    disclosures: list[Disclosure] = []
    project = result.get("project")
    if isinstance(project, dict):
        disclosure = _disclosure_from_record(project, "project", project)
        if disclosure is not None:
            disclosures.append(disclosure)

    for project_record in result.get("projects", []):
        if isinstance(project_record, dict):
            disclosure = _disclosure_from_record(project_record, "project", project_record)
            if disclosure is not None:
                disclosures.append(disclosure)

    for record_type in ("licenses", "contracts", "risks"):
        for record in result.get(record_type, []):
            if isinstance(record, dict):
                disclosure = _disclosure_from_record(record, record_type[:-1], None)
                if disclosure is not None:
                    disclosures.append(disclosure)

    return disclosures


def _disclosure_from_record(
    record: dict[str, Any],
    record_type: str,
    project: dict[str, Any] | None,
) -> Disclosure | None:
    project_id = project.get("id") if project is not None else record.get("project_id")
    record_id = record.get("id")
    if project_id is None:
        return None
    return Disclosure(
        project_id=int(project_id),
        record_type=record_type,
        record_id=int(record_id) if record_id is not None else None,
        decision="allowed",
        reason="project_visible",
    )
