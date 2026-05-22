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
from legal_mcp.policy import (
    AccessContext,
    can_query_content,
    project_is_visible,
    visible_project_ids,
)


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


def test_from_user_normalizes_required_identity_fields() -> None:
    context = AccessContext.from_user(
        {"id": "42", "role": ROLE_BUSINESS, "email": "business@example.com"},
        api_key_id=7,
    )

    assert context.user_id == 42
    assert context.role == ROLE_BUSINESS
    assert context.email == "business@example.com"
    assert context.api_key_id == 7


def test_legacy_context_is_unrestricted_and_can_query_content(
    conn: sqlite3.Connection,
) -> None:
    project_id = _project(conn, "GAME-001")
    context = AccessContext.legacy()

    assert can_query_content(context) is True
    assert visible_project_ids(conn, context) is None
    assert project_is_visible(conn, context, project_id) is True


def test_none_context_is_unrestricted_and_can_query_content(
    conn: sqlite3.Connection,
) -> None:
    project_id = _project(conn, "GAME-001")

    assert can_query_content(None) is True
    assert visible_project_ids(conn, None) is None
    assert project_is_visible(conn, None, project_id) is True


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
    assert project_is_visible(conn, context, visible_project_id) is True
    assert project_is_visible(conn, context, hidden_project_id) is False


def test_business_with_no_grants_gets_empty_visible_project_ids(
    conn: sqlite3.Connection,
) -> None:
    project_id = _project(conn, "GAME-001")
    business_user = create_user(
        conn,
        email="business@example.com",
        display_name="Business User",
        role=ROLE_BUSINESS,
    )

    context = AccessContext.from_user(business_user)

    assert visible_project_ids(conn, context) == set()
    assert project_is_visible(conn, context, project_id) is False


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
