"""MCP tool definitions and execution."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from legal_mcp import db
from legal_mcp.audit import DEFAULT_AUDIT_PATH, write_audit_record
from legal_mcp.lookup import ProjectLookupResult, lookup_project


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
) -> dict[str, Any]:
    rationale = arguments.get("rationale")
    source_client = arguments.get("source_client")
    if not isinstance(rationale, str) or not rationale.strip():
        result = _error("missing_rationale", "rationale is required")
        _audit(tool_name, rationale, source_client, arguments, result, audit_path)
        return result

    try:
        conn = db.connect(database_path)
        try:
            if tool_name == "list_projects":
                result = _list_projects(conn, arguments)
            elif tool_name == "get_project_context":
                result = _get_project_context(conn, arguments)
            elif tool_name == "list_expiring_licenses":
                result = _list_expiring_licenses(conn, arguments)
            elif tool_name == "list_open_risks":
                result = _list_open_risks(conn, arguments)
            else:
                result = _error("validation_error", f"unknown tool: {tool_name}")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        result = _error("database_error", "database operation failed", details={"reason": str(exc)})

    _audit(tool_name, rationale, source_client, arguments, result, audit_path)
    return result


def _list_projects(conn: sqlite3.Connection, arguments: dict[str, Any]) -> dict[str, Any]:
    stage = arguments.get("stage")
    if stage:
        rows = conn.execute(
            "select * from projects where stage = ? order by project_code",
            (stage,),
        ).fetchall()
    else:
        rows = conn.execute("select * from projects order by project_code").fetchall()
    return {"projects": [dict(row) for row in rows]}


def _get_project_context(conn: sqlite3.Connection, arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments.get("project_id_or_name")
    if not isinstance(query, str) or not query.strip():
        return _error("validation_error", "project_id_or_name is required")

    lookup = lookup_project(conn, query)
    if lookup.kind == ProjectLookupResult.NOT_FOUND:
        return _error("not_found", "project not found")
    if lookup.kind == ProjectLookupResult.AMBIGUOUS:
        return _error(
            "ambiguous_project",
            "project lookup is ambiguous",
            candidates=lookup.candidates or [],
        )

    project = lookup.project or {}
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


def _list_expiring_licenses(conn: sqlite3.Connection, arguments: dict[str, Any]) -> dict[str, Any]:
    days_ahead = arguments.get("days_ahead", 30)
    if not isinstance(days_ahead, int) or days_ahead < 0:
        return _error("validation_error", "days_ahead must be a non-negative integer")
    start = date.today().isoformat()
    end = (date.today() + timedelta(days=days_ahead)).isoformat()
    rows = conn.execute(
        """
        select licenses.*, projects.project_code, projects.name as project_name
        from licenses
        join projects on projects.id = licenses.project_id
        where licenses.expiry_date is not null
          and licenses.expiry_date >= ?
          and licenses.expiry_date <= ?
        order by licenses.expiry_date, projects.project_code, licenses.external_key
        """,
        (start, end),
    ).fetchall()
    return {"licenses": [dict(row) for row in rows]}


def _list_open_risks(conn: sqlite3.Connection, arguments: dict[str, Any]) -> dict[str, Any]:
    project_code = arguments.get("project_code")
    if project_code:
        rows = conn.execute(
            """
            select risks.*, projects.project_code, projects.name as project_name
            from risks
            join projects on projects.id = risks.project_id
            where risks.status = 'open' and projects.project_code = ?
            order by projects.project_code, risks.external_key
            """,
            (project_code,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            select risks.*, projects.project_code, projects.name as project_name
            from risks
            join projects on projects.id = risks.project_id
            where risks.status = 'open'
            order by projects.project_code, risks.external_key
            """
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
