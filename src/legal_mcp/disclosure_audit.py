"""Database-backed audit logging for tool result disclosures."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from legal_mcp.audit import summarize_arguments
from legal_mcp.policy import AccessContext


@dataclass(frozen=True)
class Disclosure:
    project_id: int | None
    record_type: str
    record_id: int | None
    decision: str
    reason: str
    field_name: str | None = None
    group_id: int | None = None


def write_audit_event(
    conn: sqlite3.Connection,
    context: AccessContext | None,
    tool_name: str,
    rationale: str | None,
    source_client: str | None,
    arguments: dict[str, Any],
    result: dict[str, Any],
    disclosures: list[Disclosure],
) -> int:
    """Persist a tool audit event and its disclosure decisions."""
    error = result.get("error")
    result_status = "error" if error else "success"
    error_code = error.get("code") if isinstance(error, dict) else None
    user_id = context.user_id if context is not None else None
    api_key_id = context.api_key_id if context is not None else None

    cursor = conn.execute(
        """
        insert into audit_events (
          user_id,
          api_key_id,
          source_client,
          tool_name,
          rationale,
          arguments_summary,
          result_status,
          error_code,
          response_record_count
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            api_key_id,
            source_client,
            tool_name,
            rationale,
            summarize_arguments(arguments),
            result_status,
            error_code,
            _count_records(result),
        ),
    )
    audit_event_id = int(cursor.lastrowid)

    conn.executemany(
        """
        insert into audit_disclosures (
          audit_event_id,
          project_id,
          record_type,
          record_id,
          field_name,
          group_id,
          decision,
          reason
        )
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                audit_event_id,
                disclosure.project_id,
                disclosure.record_type,
                disclosure.record_id,
                disclosure.field_name,
                disclosure.group_id,
                disclosure.decision,
                disclosure.reason,
            )
            for disclosure in disclosures
        ],
    )
    conn.commit()
    return audit_event_id


def list_audit_events(
    conn: sqlite3.Connection,
    user_id: int | None = None,
    project_id: int | None = None,
    tool_name: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List persisted audit events with optional filters."""
    filters: list[str] = []
    params: list[Any] = []

    if user_id is not None:
        filters.append("audit_events.user_id = ?")
        params.append(user_id)
    if project_id is not None:
        filters.append(
            """
            exists (
              select 1
              from audit_disclosures
              where audit_disclosures.audit_event_id = audit_events.id
                and audit_disclosures.project_id = ?
            )
            """
        )
        params.append(project_id)
    if tool_name is not None:
        filters.append("audit_events.tool_name = ?")
        params.append(tool_name)

    normalized_limit = _normalize_limit(limit)
    where_clause = f"where {' and '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"""
        select
          audit_events.*,
          users.email as email
        from audit_events
        left join users on users.id = audit_events.user_id
        {where_clause}
        order by audit_events.timestamp desc, audit_events.id desc
        limit ?
        """,
        (*params, normalized_limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _count_records(result: dict[str, Any]) -> int:
    if result.get("error"):
        return 0

    count = 0
    for value in result.values():
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += 1
    return count


def _normalize_limit(limit: int) -> int:
    return min(max(int(limit), 1), 500)
