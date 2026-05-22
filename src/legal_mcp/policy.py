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
            user_id=user.get("id"),
            role=user["role"],
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


def visible_project_ids(
    conn: sqlite3.Connection,
    context: AccessContext | None,
) -> set[int] | None:
    if context is None or context.legacy_shared_token:
        return None

    if context.role in {ROLE_ADMIN, ROLE_LEGAL}:
        rows = conn.execute("select id from projects").fetchall()
        return {int(row["id"]) for row in rows}

    if context.role == ROLE_BUSINESS and context.user_id is not None:
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
