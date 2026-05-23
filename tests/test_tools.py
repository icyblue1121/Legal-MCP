from datetime import date, timedelta

from legal_mcp import db
from legal_mcp.identity import ROLE_AUDITOR, ROLE_BUSINESS, ROLE_LEGAL, create_user
from legal_mcp.policy import AccessContext
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


def grant_project_access(conn, *, user_id: int, project_id: int) -> None:
    grantor = create_user(
        conn,
        email=f"grantor-{user_id}-{project_id}@example.com",
        display_name="Grantor",
        role=ROLE_LEGAL,
    )
    conn.execute(
        """
        insert into project_access (user_id, project_id, granted_by_user_id)
        values (?, ?, ?)
        """,
        (user_id, project_id, grantor["id"]),
    )
    conn.commit()


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


def test_get_project_fields_includes_requested_project_fields(tmp_path) -> None:
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
        "get_project_fields",
        {
            "project_id_or_name": "GAME-001",
            "fields": ["legal_bp", "department", "release_team", "contact_person", "website"],
            "rationale": "draft contract context",
        },
        database_path=database_path,
    )

    assert result["project"]["project_code"] == "GAME-001"
    assert result["project"]["legal_bp"] == "Ava"
    assert result["project"]["department"] == "Publishing"
    assert result["project"]["release_team"] == "Release A"
    assert result["project"]["contact_person"] == "Morgan"
    assert result["project"]["website"] == "https://example.test"


def test_resolve_project_returns_identity_fields(
    tmp_path,
) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        seed_project(conn, code="MGAME", name="MGame")
    finally:
        conn.close()

    result = call_tool(
        "resolve_project",
        {
            "query": "MGAME",
            "rationale": "query official website",
        },
        database_path=database_path,
    )

    assert result == {
        "project": {
            "project_code": "MGAME",
            "name": "MGame",
        }
    }


def test_get_project_fields_requires_fields(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        seed_project(conn, code="MGAME", name="MGame")
    finally:
        conn.close()

    result = call_tool(
        "get_project_fields",
        {"project_id_or_name": "MGAME", "rationale": "query project"},
        database_path=database_path,
    )

    assert result["error"]["code"] == "validation_error"


def test_get_project_fields_returns_only_requested_fields(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        seed_project(conn, code="MGAME", name="MGame")
    finally:
        conn.close()

    result = call_tool(
        "get_project_fields",
        {
            "project_id_or_name": "MGAME",
            "fields": ["website"],
            "rationale": "query official website",
        },
        database_path=database_path,
    )

    assert result == {
        "project": {
            "project_code": "MGAME",
            "name": "MGame",
            "website": "https://example.test",
        }
    }


def test_get_project_context_rejects_full_context_calls(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        seed_project(conn, code="MGAME", name="MGame")
    finally:
        conn.close()

    result = call_tool(
        "get_project_context",
        {"project_id_or_name": "MGAME", "rationale": "legacy query"},
        database_path=database_path,
    )

    assert result["error"]["code"] == "deprecated_tool"


def test_resolve_project_returns_not_found_for_ambiguous_project(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        seed_project(conn, code="GAME-001", name="Shared Name")
        seed_project(conn, code="GAME-002", name="Shared Name")
    finally:
        conn.close()

    result = call_tool(
        "resolve_project",
        {"query": "Shared Name", "rationale": "review status"},
        database_path=database_path,
    )

    assert result["error"]["code"] == "not_found"


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


def test_list_expiring_licenses_filters_to_business_project_access_grants(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    expiry_date = (date.today() + timedelta(days=7)).isoformat()
    conn = db.connect(database_path)
    try:
        visible_project_id = seed_project(conn, code="GAME-001", name="Visible Project")
        hidden_project_id = seed_project(conn, code="GAME-002", name="Hidden Project")
        conn.executemany(
            """
            insert into licenses (
              project_id, external_key, license_type, identifier, expiry_date
            )
            values (?, ?, ?, ?, ?)
            """,
            [
                (visible_project_id, "visible-license", "publication", "A", expiry_date),
                (hidden_project_id, "hidden-license", "publication", "B", expiry_date),
            ],
        )
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        grant_project_access(conn, user_id=business_user["id"], project_id=visible_project_id)
        context = AccessContext.from_user(business_user)
        conn.commit()
    finally:
        conn.close()

    result = call_tool(
        "list_expiring_licenses",
        {"days_ahead": 30, "rationale": "renewal planning"},
        database_path=database_path,
        access_context=context,
    )

    assert [license_["external_key"] for license_ in result["licenses"]] == [
        "visible-license"
    ]
    assert [license_["project_code"] for license_ in result["licenses"]] == ["GAME-001"]


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


def test_list_open_risks_filters_to_business_project_access_grants(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        visible_project_id = seed_project(conn, code="GAME-001", name="Visible Project")
        hidden_project_id = seed_project(conn, code="GAME-002", name="Hidden Project")
        conn.executemany(
            """
            insert into risks (project_id, external_key, description, status)
            values (?, ?, ?, ?)
            """,
            [
                (visible_project_id, "visible-risk", "Needs review", "open"),
                (hidden_project_id, "hidden-risk", "Also needs review", "open"),
            ],
        )
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        grant_project_access(conn, user_id=business_user["id"], project_id=visible_project_id)
        context = AccessContext.from_user(business_user)
        conn.commit()
    finally:
        conn.close()

    result = call_tool(
        "list_open_risks",
        {"rationale": "prepare weekly summary"},
        database_path=database_path,
        access_context=context,
    )
    filtered_result = call_tool(
        "list_open_risks",
        {"project_code": "GAME-001", "rationale": "prepare weekly summary"},
        database_path=database_path,
        access_context=context,
    )

    assert [risk["external_key"] for risk in result["risks"]] == ["visible-risk"]
    assert [risk["project_code"] for risk in result["risks"]] == ["GAME-001"]
    assert [risk["external_key"] for risk in filtered_result["risks"]] == [
        "visible-risk"
    ]
    assert [risk["project_code"] for risk in filtered_result["risks"]] == ["GAME-001"]


def test_list_projects_filters_to_business_project_access_grants(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        visible_project_id = seed_project(conn, code="GAME-001", name="Visible Project")
        seed_project(conn, code="GAME-002", name="Hidden Project")
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        grant_project_access(conn, user_id=business_user["id"], project_id=visible_project_id)
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    result = call_tool(
        "list_projects",
        {"rationale": "review accessible projects"},
        database_path=database_path,
        access_context=context,
    )

    assert [project["project_code"] for project in result["projects"]] == ["GAME-001"]


def test_get_project_fields_returns_not_found_for_hidden_project(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        seed_project(conn, code="GAME-001", name="Visible Project")
        seed_project(conn, code="GAME-002", name="Hidden Project")
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    result = call_tool(
        "get_project_fields",
        {
            "project_id_or_name": "GAME-002",
            "fields": ["website"],
            "rationale": "review project context",
        },
        database_path=database_path,
        access_context=context,
    )

    assert result["error"]["code"] == "not_found"


def test_get_project_fields_returns_not_found_when_name_is_ambiguous(
    tmp_path,
) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        visible_project_id = seed_project(conn, code="GAME-001", name="Shared Name")
        seed_project(conn, code="GAME-002", name="Shared Name")
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        grant_project_access(conn, user_id=business_user["id"], project_id=visible_project_id)
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    result = call_tool(
        "get_project_fields",
        {
            "project_id_or_name": "Shared Name",
            "fields": ["website"],
            "rationale": "review project context",
        },
        database_path=database_path,
        access_context=context,
    )

    assert result["error"]["code"] == "not_found"


def test_get_project_fields_returns_not_found_for_ambiguous_visible_projects(
    tmp_path,
) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        visible_project_id = seed_project(conn, code="GAME-001", name="Shared Name")
        other_visible_project_id = seed_project(conn, code="GAME-002", name="Shared Name")
        seed_project(conn, code="GAME-003", name="Shared Name")
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        grant_project_access(conn, user_id=business_user["id"], project_id=visible_project_id)
        grant_project_access(
            conn,
            user_id=business_user["id"],
            project_id=other_visible_project_id,
        )
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    result = call_tool(
        "get_project_fields",
        {
            "project_id_or_name": "Shared Name",
            "fields": ["website"],
            "rationale": "review project context",
        },
        database_path=database_path,
        access_context=context,
    )

    assert result["error"]["code"] == "not_found"


def test_get_project_fields_hidden_ambiguous_candidates_return_not_found(
    tmp_path,
) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        seed_project(conn, code="GAME-001", name="Shared Name")
        seed_project(conn, code="GAME-002", name="Shared Name")
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    result = call_tool(
        "get_project_fields",
        {
            "project_id_or_name": "Shared Name",
            "fields": ["website"],
            "rationale": "review project context",
        },
        database_path=database_path,
        access_context=context,
    )

    assert result["error"]["code"] == "not_found"
    assert result["error"]["candidates"] == []


def test_legal_user_list_projects_filters_to_project_access_grants(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        visible_project_id = seed_project(conn, code="GAME-001", name="First Project")
        seed_project(conn, code="GAME-002", name="Second Project")
        legal_user = create_user(
            conn,
            email="legal@example.com",
            display_name="Legal User",
            role=ROLE_LEGAL,
        )
        grant_project_access(conn, user_id=legal_user["id"], project_id=visible_project_id)
        context = AccessContext.from_user(legal_user)
    finally:
        conn.close()

    result = call_tool(
        "list_projects",
        {"rationale": "review accessible projects"},
        database_path=database_path,
        access_context=context,
    )

    assert [project["project_code"] for project in result["projects"]] == ["GAME-001"]


def test_legal_user_get_project_fields_returns_not_found_for_hidden_project(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        visible_project_id = seed_project(conn, code="MGAME", name="MGame")
        seed_project(conn, code="OTHER", name="Other Project")
        legal_user = create_user(
            conn,
            email="legal@test.com",
            display_name="Legal User",
            role=ROLE_LEGAL,
        )
        grant_project_access(conn, user_id=legal_user["id"], project_id=visible_project_id)
        context = AccessContext.from_user(legal_user)
    finally:
        conn.close()

    result = call_tool(
        "get_project_fields",
        {
            "project_id_or_name": "OTHER",
            "fields": ["website"],
            "rationale": "review project context",
        },
        database_path=database_path,
        access_context=context,
    )

    assert result["error"]["code"] == "not_found"


def test_auditor_cannot_call_content_tools(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        seed_project(conn)
        auditor_user = create_user(
            conn,
            email="auditor@example.com",
            display_name="Auditor User",
            role=ROLE_AUDITOR,
        )
        context = AccessContext.from_user(auditor_user)
    finally:
        conn.close()

    for tool_name, arguments in {
        "list_projects": {"rationale": "audit project list"},
        "get_project_context": {
            "project_id_or_name": "GAME-001",
            "rationale": "audit project details",
        },
        "list_expiring_licenses": {"rationale": "audit license list"},
        "list_open_risks": {"rationale": "audit risk list"},
    }.items():
        result = call_tool(
            tool_name,
            arguments,
            database_path=database_path,
            access_context=context,
        )

        assert result["error"]["code"] == "access_denied"
