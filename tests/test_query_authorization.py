from __future__ import annotations

from pathlib import Path

from legal_mcp import db
from legal_mcp.identity import ROLE_LEGAL, create_user
from legal_mcp.policy import AccessContext
from legal_mcp.query_authorization import authorize_query_plan
from legal_mcp.query_plan import QueryFilter, QueryPlan


def _seed_user_without_project_field(
    tmp_path: Path,
    *,
    denied_field: str,
    granted_fields: set[str],
):
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    project_id = conn.execute(
        """
        insert into projects (project_code, name, stage, legal_bp, website)
        values (?, ?, ?, ?, ?)
        """,
        ("MGAME", "失序之地", "live", "张三", "https://mgame.example"),
    ).lastrowid
    user = create_user(
        conn,
        email=f"legal-{denied_field}@example.com",
        display_name="Legal User",
        role=ROLE_LEGAL,
    )
    grantor = create_user(
        conn,
        email=f"grantor-{denied_field}@example.com",
        display_name="Grantor",
        role=ROLE_LEGAL,
    )
    conn.execute(
        """
        insert into project_access (user_id, project_id, granted_by_user_id)
        values (?, ?, ?)
        """,
        (user["id"], project_id, grantor["id"]),
    )
    group_id = conn.execute(
        "insert into user_groups (name) values (?)",
        (f"group-{denied_field}",),
    ).lastrowid
    conn.execute(
        "insert into user_group_memberships (user_id, group_id) values (?, ?)",
        (user["id"], group_id),
    )
    for field in sorted(granted_fields):
        conn.execute(
            """
            insert into permission_grants
              (group_id, operation, data_domain, field_name, project_id)
            values (?, ?, ?, ?, ?)
            """,
            (group_id, "read", "project", field, project_id),
        )
    conn.commit()
    return conn, AccessContext.from_user(user)


def test_filter_field_requires_read_permission(tmp_path: Path) -> None:
    conn, context = _seed_user_without_project_field(
        tmp_path,
        denied_field="legal_bp",
        granted_fields={"website"},
    )
    try:
        plan = QueryPlan(
            domain="project",
            operation="search",
            filters=[QueryFilter(field="legal_bp", operator="eq", value="张三")],
            return_fields=["project_code", "name"],
            limit=20,
        )

        result = authorize_query_plan(conn, plan, context)
    finally:
        conn.close()

    assert result.ok is False
    assert result.error_code == "filter_field_access_denied"
    assert result.disclosures[0].field_name == "legal_bp"
    assert result.disclosures[0].decision == "denied"


def test_return_field_requires_read_permission(tmp_path: Path) -> None:
    conn, context = _seed_user_without_project_field(
        tmp_path,
        denied_field="website",
        granted_fields={"legal_bp"},
    )
    try:
        plan = QueryPlan(
            domain="project",
            operation="search",
            filters=[QueryFilter(field="legal_bp", operator="eq", value="张三")],
            return_fields=["project_code", "name", "website"],
            limit=20,
        )

        result = authorize_query_plan(conn, plan, context)
    finally:
        conn.close()

    assert result.ok is False
    assert result.error_code == "return_field_access_denied"
    assert result.disclosures[0].field_name == "website"
    assert result.disclosures[0].decision == "denied"
