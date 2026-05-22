from __future__ import annotations

import sqlite3

import pytest

from legal_mcp import db
from legal_mcp.identity import (
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_BUSINESS,
    ROLE_LEGAL,
    create_user,
)
from legal_mcp.policy import AccessContext, can_query_content, visible_project_ids


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    db_path = tmp_path / "legal.db"
    db.initialize_database(db_path)
    connection = db.connect(db_path)
    try:
        yield connection
    finally:
        connection.close()


def _project(conn: sqlite3.Connection, code: str) -> int:
    cursor = conn.execute(
        "insert into projects (project_code, name, stage) values (?, ?, ?)",
        (code, f"{code} Project", "live"),
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_legal_and_admin_can_see_all_projects_and_query_content(
    conn: sqlite3.Connection,
) -> None:
    project_ids = {_project(conn, "GAME-001"), _project(conn, "GAME-002")}
    legal_user = create_user(
        conn,
        email="legal@example.com",
        display_name="Legal User",
        role=ROLE_LEGAL,
    )
    admin_user = create_user(
        conn,
        email="admin@example.com",
        display_name="Admin User",
        role=ROLE_ADMIN,
    )

    legal_context = AccessContext.from_user(legal_user)
    admin_context = AccessContext.from_user(admin_user)

    assert can_query_content(legal_context) is True
    assert visible_project_ids(conn, legal_context) == project_ids
    assert can_query_content(admin_context) is True
    assert visible_project_ids(conn, admin_context) == project_ids


def test_business_can_see_only_project_access_grants_and_query_content(
    conn: sqlite3.Connection,
) -> None:
    visible_project_id = _project(conn, "GAME-001")
    hidden_project_id = _project(conn, "GAME-002")
    grantor = create_user(
        conn,
        email="legal@example.com",
        display_name="Legal User",
        role=ROLE_LEGAL,
    )
    business_user = create_user(
        conn,
        email="business@example.com",
        display_name="Business User",
        role=ROLE_BUSINESS,
    )
    conn.execute(
        """
        insert into project_access (user_id, project_id, granted_by_user_id)
        values (?, ?, ?)
        """,
        (business_user["id"], visible_project_id, grantor["id"]),
    )
    conn.commit()

    context = AccessContext.from_user(business_user)

    assert can_query_content(context) is True
    assert visible_project_ids(conn, context) == {visible_project_id}
    assert hidden_project_id not in visible_project_ids(conn, context)


def test_auditor_visible_project_ids_is_empty_and_cannot_query_content(
    conn: sqlite3.Connection,
) -> None:
    _project(conn, "GAME-001")
    auditor_user = create_user(
        conn,
        email="auditor@example.com",
        display_name="Auditor User",
        role=ROLE_AUDITOR,
    )

    context = AccessContext.from_user(auditor_user)

    assert can_query_content(context) is False
    assert visible_project_ids(conn, context) == set()
