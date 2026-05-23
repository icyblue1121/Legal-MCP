import json

from legal_mcp import db
from legal_mcp.identity import ROLE_AUDITOR, ROLE_BUSINESS, ROLE_LEGAL, create_user
from legal_mcp.policy import AccessContext
from legal_mcp.tools import call_tool


def test_audit_log_records_successful_and_failed_tool_calls(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Project One", "live"),
        )
        conn.commit()
    finally:
        conn.close()

    call_tool(
        "list_projects",
        {"rationale": "status review", "source_client": "pytest"},
        database_path=database_path,
        audit_path=audit_path,
    )
    call_tool(
        "get_project_context",
        {"project_id_or_name": "Missing", "rationale": "status review"},
        database_path=database_path,
        audit_path=audit_path,
    )

    records = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert records[0]["tool_name"] == "list_projects"
    assert records[0]["rationale"] == "status review"
    assert records[0]["source_client"] == "pytest"
    assert records[0]["result_status"] == "success"
    assert records[0]["error_code"] is None
    assert records[1]["tool_name"] == "get_project_context"
    assert records[1]["result_status"] == "error"
    assert records[1]["error_code"] == "not_found"
    assert "Missing" in records[1]["arguments_summary"]


def test_tool_call_writes_database_audit_event_and_project_disclosure(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        project_id = conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Project One", "live"),
        ).lastrowid
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        legal_user = create_user(
            conn,
            email="legal@example.com",
            display_name="Legal User",
            role=ROLE_LEGAL,
        )
        conn.execute(
            """
            insert into project_access (user_id, project_id, granted_by_user_id)
            values (?, ?, ?)
            """,
            (business_user["id"], project_id, legal_user["id"]),
        )
        conn.commit()
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    call_tool(
        "get_project_context",
        {
            "project_id_or_name": "GAME-001",
            "rationale": "prepare business summary",
            "source_client": "pytest-client",
        },
        database_path=database_path,
        audit_path=audit_path,
        access_context=context,
    )

    conn = db.connect(database_path)
    try:
        event = conn.execute("select * from audit_events").fetchone()
        disclosure = conn.execute("select * from audit_disclosures").fetchone()
    finally:
        conn.close()

    assert event["user_id"] == business_user["id"]
    assert event["tool_name"] == "get_project_context"
    assert event["rationale"] == "prepare business summary"
    assert event["source_client"] == "pytest-client"
    assert disclosure["project_id"] == project_id
    assert disclosure["record_type"] == "project"
    assert disclosure["decision"] == "allowed"


def test_hidden_project_lookup_records_denied_disclosure_without_leaking_project(
    tmp_path,
) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        hidden_project_id = conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-002", "Hidden Project", "live"),
        ).lastrowid
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        conn.commit()
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    result = call_tool(
        "get_project_context",
        {"project_id_or_name": "GAME-002", "rationale": "prepare business summary"},
        database_path=database_path,
        access_context=context,
    )

    conn = db.connect(database_path)
    try:
        event = conn.execute("select * from audit_events").fetchone()
        disclosure = conn.execute("select * from audit_disclosures").fetchone()
    finally:
        conn.close()

    assert result["error"]["code"] == "not_found"
    assert result["error"]["candidates"] == []
    assert result["error"]["details"] == {}
    assert event["result_status"] == "error"
    assert event["error_code"] == "not_found"
    assert disclosure["project_id"] == hidden_project_id
    assert disclosure["record_type"] == "project"
    assert disclosure["decision"] == "denied"


def test_hidden_ambiguous_lookup_records_denied_disclosures_without_candidates(
    tmp_path,
) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        first_project_id = conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Shared Name", "live"),
        ).lastrowid
        second_project_id = conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-002", "Shared Name", "live"),
        ).lastrowid
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        conn.commit()
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    result = call_tool(
        "get_project_context",
        {"project_id_or_name": "Shared Name", "rationale": "prepare business summary"},
        database_path=database_path,
        access_context=context,
    )

    conn = db.connect(database_path)
    try:
        disclosures = conn.execute(
            "select project_id, record_type, decision from audit_disclosures order by project_id"
        ).fetchall()
    finally:
        conn.close()

    assert result["error"]["code"] == "not_found"
    assert result["error"]["candidates"] == []
    assert [disclosure["project_id"] for disclosure in disclosures] == [
        first_project_id,
        second_project_id,
    ]
    assert {disclosure["record_type"] for disclosure in disclosures} == {"project"}
    assert {disclosure["decision"] for disclosure in disclosures} == {"denied"}


def test_visible_ambiguous_lookup_records_allowed_candidate_disclosures(
    tmp_path,
) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        first_project_id = conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Shared Name", "live"),
        ).lastrowid
        second_project_id = conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-002", "Shared Name", "live"),
        ).lastrowid
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        legal_user = create_user(
            conn,
            email="legal@example.com",
            display_name="Legal User",
            role=ROLE_LEGAL,
        )
        conn.executemany(
            """
            insert into project_access (user_id, project_id, granted_by_user_id)
            values (?, ?, ?)
            """,
            [
                (business_user["id"], first_project_id, legal_user["id"]),
                (business_user["id"], second_project_id, legal_user["id"]),
            ],
        )
        conn.commit()
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    result = call_tool(
        "get_project_context",
        {"project_id_or_name": "Shared Name", "rationale": "prepare business summary"},
        database_path=database_path,
        access_context=context,
    )

    conn = db.connect(database_path)
    try:
        disclosures = conn.execute(
            """
            select project_id, record_type, record_id, decision, reason
            from audit_disclosures
            order by project_id
            """
        ).fetchall()
    finally:
        conn.close()

    assert result["error"]["code"] == "ambiguous_project"
    assert [candidate["project_code"] for candidate in result["error"]["candidates"]] == [
        "GAME-001",
        "GAME-002",
    ]
    assert [disclosure["project_id"] for disclosure in disclosures] == [
        first_project_id,
        second_project_id,
    ]
    assert [disclosure["record_id"] for disclosure in disclosures] == [
        first_project_id,
        second_project_id,
    ]
    assert {disclosure["record_type"] for disclosure in disclosures} == {"project"}
    assert {disclosure["decision"] for disclosure in disclosures} == {"allowed"}
    assert {disclosure["reason"] for disclosure in disclosures} == {"project_visible"}


def test_open_risks_hidden_project_code_records_denied_disclosure_without_leak(
    tmp_path,
) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        visible_project_id = conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Visible Project", "live"),
        ).lastrowid
        hidden_project_id = conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-002", "Hidden Project", "live"),
        ).lastrowid
        conn.execute(
            "insert into risks (project_id, external_key, description, status) values (?, ?, ?, ?)",
            (hidden_project_id, "hidden-risk", "Hidden risk", "open"),
        )
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        legal_user = create_user(
            conn,
            email="legal@example.com",
            display_name="Legal User",
            role=ROLE_LEGAL,
        )
        conn.execute(
            """
            insert into project_access (user_id, project_id, granted_by_user_id)
            values (?, ?, ?)
            """,
            (business_user["id"], visible_project_id, legal_user["id"]),
        )
        conn.commit()
        context = AccessContext.from_user(business_user)
    finally:
        conn.close()

    result = call_tool(
        "list_open_risks",
        {"project_code": "GAME-002", "rationale": "prepare business summary"},
        database_path=database_path,
        access_context=context,
    )

    conn = db.connect(database_path)
    try:
        disclosure = conn.execute(
            "select project_id, record_type, record_id, decision, reason from audit_disclosures"
        ).fetchone()
    finally:
        conn.close()

    assert result == {"risks": []}
    assert disclosure["project_id"] == hidden_project_id
    assert disclosure["record_type"] == "project"
    assert disclosure["record_id"] == hidden_project_id
    assert disclosure["decision"] == "denied"
    assert disclosure["reason"] == "project_hidden"


def test_auditor_denial_records_database_audit_event_without_disclosure(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        auditor_user = create_user(
            conn,
            email="auditor@example.com",
            display_name="Auditor User",
            role=ROLE_AUDITOR,
        )
        context = AccessContext.from_user(auditor_user)
    finally:
        conn.close()

    result = call_tool(
        "get_project_context",
        {"project_id_or_name": "GAME-001", "rationale": "audit project details"},
        database_path=database_path,
        access_context=context,
    )

    conn = db.connect(database_path)
    try:
        event = conn.execute("select * from audit_events").fetchone()
        disclosure_count = conn.execute("select count(*) from audit_disclosures").fetchone()[0]
    finally:
        conn.close()

    assert result["error"]["code"] == "access_denied"
    assert event["user_id"] == auditor_user["id"]
    assert event["tool_name"] == "get_project_context"
    assert event["result_status"] == "error"
    assert event["error_code"] == "access_denied"
    assert disclosure_count == 0
