"""Project access policy helpers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from legal_mcp.identity import ROLE_ADMIN, ROLE_BUSINESS, ROLE_LEGAL


@dataclass(frozen=True)
class AccessContext:
    user_id: int | None
    role: str
    email: str | None = None
    api_key_id: int | None = None
    legacy_shared_token: bool = False

    @classmethod
    def from_user(
        cls,
        user: dict[str, Any],
        api_key_id: int | None = None,
    ) -> "AccessContext":
        return cls(
            user_id=int(user["id"]),
            role=str(user["role"]),
            email=user.get("email"),
            api_key_id=api_key_id,
        )

    @classmethod
    def legacy(cls) -> "AccessContext":
        return cls(
            user_id=None,
            role=ROLE_LEGAL,
            legacy_shared_token=True,
        )


def can_query_content(context: AccessContext | None) -> bool:
    if context is None:
        return True
    return context.role in {ROLE_ADMIN, ROLE_LEGAL, ROLE_BUSINESS}


@dataclass(frozen=True)
class FieldAuthorizationDecision:
    allowed_fields: set[str]
    denied_fields: dict[str, str]


def visible_project_ids(
    conn: sqlite3.Connection,
    context: AccessContext | None,
) -> set[int] | None:
    if context is None or context.legacy_shared_token:
        return None

    if context.role == ROLE_ADMIN:
        rows = conn.execute("select id from projects").fetchall()
        return {int(row["id"]) for row in rows}

    if context.role in {ROLE_BUSINESS, ROLE_LEGAL} and context.user_id is not None:
        rows = conn.execute(
            "select project_id from project_access where user_id = ?",
            (context.user_id,),
        ).fetchall()
        return {int(row["project_id"]) for row in rows}

    return set()


def project_is_visible(
    conn: sqlite3.Connection,
    context: AccessContext | None,
    project_id: int,
) -> bool:
    visible_ids = visible_project_ids(conn, context)
    if visible_ids is None:
        return True
    return project_id in visible_ids


def user_group_ids(conn: sqlite3.Connection, context: AccessContext | None) -> set[int]:
    if context is None or context.user_id is None:
        return set()
    rows = conn.execute(
        "select group_id from user_group_memberships where user_id = ?",
        (context.user_id,),
    ).fetchall()
    return {int(row["group_id"]) for row in rows}


def authorize_fields(
    conn: sqlite3.Connection,
    context: AccessContext | None,
    *,
    operation: str,
    data_domain: str,
    project_id: int | None,
    requested_fields: set[str],
) -> FieldAuthorizationDecision:
    if context is None or context.legacy_shared_token:
        return FieldAuthorizationDecision(set(requested_fields), {})
    if context.role == ROLE_ADMIN:
        return FieldAuthorizationDecision(set(requested_fields), {})

    group_ids = user_group_ids(conn, context)
    if not group_ids:
        return FieldAuthorizationDecision(
            set(),
            {field: "no_group_membership" for field in requested_fields},
        )

    placeholders = ", ".join("?" for _ in group_ids)
    params: list[object] = [*sorted(group_ids), operation, data_domain, project_id]
    rows = conn.execute(
        f"""
        select field_name
        from permission_grants
        where group_id in ({placeholders})
          and operation = ?
          and data_domain = ?
          and (project_id is null or project_id = ?)
          and allowed = 1
        """,
        params,
    ).fetchall()

    # A grant row with NULL field_name authorizes every field in the domain.
    # describe_my_access treats NULL the same way; authorize_fields must agree,
    # otherwise a domain-wide grant would deny every specific field.
    if any(row["field_name"] is None for row in rows):
        return FieldAuthorizationDecision(set(requested_fields), {})

    granted = {str(row["field_name"]) for row in rows if row["field_name"]}
    allowed = requested_fields & granted
    denied = {
        field: "field_not_granted"
        for field in requested_fields
        if field not in allowed
    }
    return FieldAuthorizationDecision(allowed, denied)
