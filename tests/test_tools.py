from datetime import date, timedelta

from legal_mcp import db
from legal_mcp.tools import call_tool


def seed_project(conn, *, code: str = "GAME-001", name: str = "Project One") -> int:
    cursor = conn.execute(
        """
        insert into projects (
          project_code, name, stage, legal_bp, department, release_team,
          contact_person, website
        )
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code,
            name,
            "live",
            "Ava",
            "Publishing",
            "Release A",
            "Morgan",
            "https://example.test",
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_all_tools_require_rationale(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)

    for tool_name, arguments in {
        "list_projects": {},
        "get_project_context": {"project_id_or_name": "GAME-001"},
        "list_expiring_licenses": {},
        "list_open_risks": {},
    }.items():
        result = call_tool(tool_name, arguments, database_path=database_path)

        assert result["error"]["code"] == "missing_rationale"


def test_get_project_context_includes_project_fields_and_all_licenses(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        project_id = seed_project(conn)
        conn.execute(
            """
            insert into licenses (
              project_id, external_key, license_type, identifier, expiry_date
            )
            values (?, ?, ?, ?, ?)
            """,
            (project_id, "publication", "publication_license", "ISBN-001", None),
        )
        conn.commit()
    finally:
        conn.close()

    result = call_tool(
        "get_project_context",
        {"project_id_or_name": "GAME-001", "rationale": "draft contract context"},
        database_path=database_path,
    )

    assert result["project"]["project_code"] == "GAME-001"
    assert result["project"]["legal_bp"] == "Ava"
    assert result["project"]["department"] == "Publishing"
    assert result["project"]["release_team"] == "Release A"
    assert result["project"]["contact_person"] == "Morgan"
    assert result["project"]["website"] == "https://example.test"
    assert result["licenses"][0]["external_key"] == "publication"
    assert result["licenses"][0]["expiry_date"] is None


def test_ambiguous_project_context_returns_structured_error(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        seed_project(conn, code="GAME-001", name="Shared Name")
        seed_project(conn, code="GAME-002", name="Shared Name")
    finally:
        conn.close()

    result = call_tool(
        "get_project_context",
        {"project_id_or_name": "Shared Name", "rationale": "review status"},
        database_path=database_path,
    )

    assert result["error"]["code"] == "ambiguous_project"
    assert [candidate["project_code"] for candidate in result["error"]["candidates"]] == [
        "GAME-001",
        "GAME-002",
    ]


def test_expiring_license_boundaries_exclude_null_and_late_dates(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    today = date.today()
    conn = db.connect(database_path)
    try:
        project_id = seed_project(conn)
        conn.executemany(
            """
            insert into licenses (
              project_id, external_key, license_type, identifier, expiry_date
            )
            values (?, ?, ?, ?, ?)
            """,
            [
                (project_id, "expires_today", "publication", "A", today.isoformat()),
                (
                    project_id,
                    "expires_boundary",
                    "publication",
                    "B",
                    (today + timedelta(days=30)).isoformat(),
                ),
                (
                    project_id,
                    "expires_late",
                    "publication",
                    "C",
                    (today + timedelta(days=31)).isoformat(),
                ),
                (project_id, "no_expiry", "publication", "D", None),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    result = call_tool(
        "list_expiring_licenses",
        {"days_ahead": 30, "rationale": "renewal planning"},
        database_path=database_path,
    )

    assert [license_["external_key"] for license_ in result["licenses"]] == [
        "expires_today",
        "expires_boundary",
    ]


def test_open_risks_exclude_closed_risks(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        project_id = seed_project(conn)
        conn.executemany(
            """
            insert into risks (project_id, external_key, description, status)
            values (?, ?, ?, ?)
            """,
            [
                (project_id, "risk-open", "Needs review", "open"),
                (project_id, "risk-closed", "Resolved", "closed"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    result = call_tool(
        "list_open_risks",
        {"project_code": "GAME-001", "rationale": "prepare weekly summary"},
        database_path=database_path,
    )

    assert [risk["external_key"] for risk in result["risks"]] == ["risk-open"]
