from __future__ import annotations

from pathlib import Path

from legal_mcp import db
from legal_mcp.identity import ROLE_LEGAL, create_user
from legal_mcp.policy import AccessContext
from legal_mcp.query_plan import QueryFilter, QueryPlan
from legal_mcp.search_tools import (
    execute_search_plan,
    search_contracts,
    search_cross_domain,
    search_licenses,
    search_projects,
)


def _seed_database(path: Path) -> AccessContext:
    db.initialize_database(path)
    conn = db.connect(path)
    try:
        visible_a = _insert_project(conn, "Mgame", "失序之地", "张三")
        visible_b = _insert_project(conn, "代号 T", "指尖魔宠", "张三")
        hidden = _insert_project(conn, "HIDDEN", "隐藏项目", "张三")
        _insert_contract(conn, visible_a, "C-001", "腾讯框架合同", "腾讯科技", "张三")
        _insert_contract(conn, visible_b, "C-002", "米哈游联运合同", "米哈游", "李四")
        _insert_contract(conn, hidden, "C-999", "隐藏合同", "腾讯科技", "张三")
        _insert_license(conn, visible_a, "L-001", "版号", "上海运营公司", "某公司")
        _insert_license(conn, visible_b, "L-002", "软著", "某公司", "某公司")
        _insert_license(conn, hidden, "L-999", "隐藏资质", "某公司", "某公司")
        user = create_user(
            conn,
            email="legal-search@example.com",
            display_name="Legal Search",
            role=ROLE_LEGAL,
        )
        grantor = create_user(
            conn,
            email="legal-search-grantor@example.com",
            display_name="Grantor",
            role=ROLE_LEGAL,
        )
        for project_id in (visible_a, visible_b):
            conn.execute(
                """
                insert into project_access (user_id, project_id, granted_by_user_id)
                values (?, ?, ?)
                """,
                (user["id"], project_id, grantor["id"]),
            )
            _grant_field(conn, user["id"], project_id, "project", "legal_bp")
            _grant_field(conn, user["id"], project_id, "contract", "counterparty")
            _grant_field(conn, user["id"], project_id, "contract", "handler")
            _grant_field(conn, user["id"], project_id, "license", "actual_operator")
            _grant_field(conn, user["id"], project_id, "license", "operating_entity")
        conn.commit()
        return AccessContext.from_user(user)
    finally:
        conn.close()


def _insert_project(conn, code: str, name: str, legal_bp: str) -> int:
    cursor = conn.execute(
        """
        insert into projects (
          project_code, name, stage, legal_bp, department, release_team
        )
        values (?, ?, ?, ?, ?, ?)
        """,
        (code, name, "live", legal_bp, "法务部", "发行中心"),
    )
    return int(cursor.lastrowid)


def _insert_contract(
    conn,
    project_id: int,
    contract_number: str,
    title: str,
    counterparty: str,
    handler: str,
) -> None:
    conn.execute(
        """
        insert into contracts (
          project_id, external_key, title, contract_number, counterparty, handler
        )
        values (?, ?, ?, ?, ?, ?)
        """,
        (project_id, contract_number, title, contract_number, counterparty, handler),
    )


def _insert_license(
    conn,
    project_id: int,
    external_key: str,
    license_type: str,
    operating_entity: str,
    actual_operator: str,
) -> None:
    conn.execute(
        """
        insert into licenses (
          project_id, external_key, license_type, operating_entity, actual_operator
        )
        values (?, ?, ?, ?, ?)
        """,
        (project_id, external_key, license_type, operating_entity, actual_operator),
    )


def _grant_field(
    conn,
    user_id: int,
    project_id: int,
    data_domain: str,
    field_name: str,
) -> None:
    group_id = conn.execute(
        "insert into user_groups (name) values (?)",
        (f"group-{user_id}-{project_id}-{data_domain}-{field_name}",),
    ).lastrowid
    conn.execute(
        "insert into user_group_memberships (user_id, group_id) values (?, ?)",
        (user_id, group_id),
    )
    conn.execute(
        """
        insert into permission_grants
          (group_id, operation, data_domain, field_name, project_id)
        values (?, ?, ?, ?, ?)
        """,
        (group_id, "read", data_domain, field_name, project_id),
    )


def test_search_projects_by_legal_bp_returns_visible_projects(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    context = _seed_database(database_path)
    conn = db.connect(database_path)
    try:
        result = search_projects(
            conn,
            QueryPlan(
                domain="project",
                operation="search",
                filters=[QueryFilter(field="legal_bp", operator="eq", value="张三")],
                return_fields=["project_code", "name"],
                limit=20,
            ),
            access_context=context,
        )
    finally:
        conn.close()

    assert result == {
        "projects": [
            {"project_code": "Mgame", "name": "失序之地"},
            {"project_code": "代号 T", "name": "指尖魔宠"},
        ]
    }


def test_search_contracts_by_counterparty_contains_respects_visibility(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    context = _seed_database(database_path)
    conn = db.connect(database_path)
    try:
        result = search_contracts(
            conn,
            QueryPlan(
                domain="contract",
                operation="search",
                filters=[QueryFilter(field="counterparty", operator="contains", value="腾讯")],
                return_fields=["contract_number", "title", "counterparty"],
                limit=20,
            ),
            access_context=context,
        )
    finally:
        conn.close()

    assert result == {
        "contracts": [
            {
                "contract_number": "C-001",
                "title": "腾讯框架合同",
                "counterparty": "腾讯科技",
            }
        ]
    }


def test_search_licenses_by_actual_operator_and_limit(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    context = _seed_database(database_path)
    conn = db.connect(database_path)
    try:
        result = search_licenses(
            conn,
            QueryPlan(
                domain="license",
                operation="search",
                filters=[QueryFilter(field="actual_operator", operator="eq", value="某公司")],
                return_fields=["license_type", "actual_operator"],
                limit=1,
            ),
            access_context=context,
        )
    finally:
        conn.close()

    assert result == {
        "licenses": [{"license_type": "版号", "actual_operator": "某公司"}]
    }


def test_search_cross_domain_matches_visible_records_only(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    context = _seed_database(database_path)
    conn = db.connect(database_path)
    try:
        result = search_cross_domain(
            conn,
            QueryPlan(
                domain="cross_domain",
                operation="search",
                filters=[QueryFilter(field="q", operator="contains", value="张三")],
                return_fields=["project_code", "name", "contract_number", "title"],
                limit=20,
            ),
            access_context=context,
        )
    finally:
        conn.close()

    assert [project["project_code"] for project in result["projects"]] == [
        "Mgame",
        "代号 T",
    ]
    assert [contract["contract_number"] for contract in result["contracts"]] == ["C-001"]
    assert result["licenses"] == []
    assert "HIDDEN" not in str(result)


def test_execute_search_plan_dispatches_by_domain(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    context = _seed_database(database_path)
    conn = db.connect(database_path)
    try:
        result = execute_search_plan(
            conn,
            QueryPlan(
                domain="project",
                operation="search",
                filters=[QueryFilter(field="legal_bp", operator="eq", value="张三")],
                return_fields=["project_code"],
                limit=1,
            ),
            access_context=context,
        )
    finally:
        conn.close()

    assert result == {"projects": [{"project_code": "Mgame"}]}
