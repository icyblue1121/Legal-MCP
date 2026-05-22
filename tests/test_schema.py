import sqlite3

import pytest

from legal_mcp import db


EXPECTED_COLUMNS = {
    "projects": [
        "id",
        "project_code",
        "name",
        "stage",
        "legal_bp",
        "department",
        "release_team",
        "contact_person",
        "website",
        "notes",
        "created_at",
        "updated_at",
    ],
    "contracts": [
        "id",
        "project_id",
        "external_key",
        "title",
        "counterparty",
        "signed_date",
        "summary",
        "created_at",
        "updated_at",
    ],
    "licenses": [
        "id",
        "project_id",
        "external_key",
        "license_type",
        "identifier",
        "entity_name",
        "issuer",
        "approval_number",
        "rights_holder",
        "copyright_holder",
        "operating_entity",
        "actual_operator",
        "authorization_relation",
        "expiry_date",
        "notes",
        "created_at",
        "updated_at",
    ],
    "risks": [
        "id",
        "project_id",
        "external_key",
        "description",
        "status",
        "source",
        "created_at",
        "updated_at",
    ],
    "users": [
        "id",
        "email",
        "display_name",
        "role",
        "status",
        "password_hash",
        "external_subject",
        "created_at",
        "updated_at",
    ],
    "api_keys": [
        "id",
        "user_id",
        "key_prefix",
        "key_hash",
        "label",
        "status",
        "last_used_at",
        "created_at",
        "revoked_at",
    ],
    "project_access": [
        "id",
        "user_id",
        "project_id",
        "granted_by_user_id",
        "created_at",
    ],
    "admin_sessions": [
        "id",
        "user_id",
        "session_hash",
        "expires_at",
        "created_at",
    ],
    "audit_events": [
        "id",
        "timestamp",
        "user_id",
        "api_key_id",
        "source_client",
        "tool_name",
        "rationale",
        "arguments_summary",
        "result_status",
        "error_code",
        "response_record_count",
    ],
    "audit_disclosures": [
        "id",
        "audit_event_id",
        "project_id",
        "record_type",
        "record_id",
        "decision",
        "reason",
    ],
}

EXPECTED_INDEXES = [
    ("projects", ("project_code",), True),
    ("projects", ("stage",), False),
    ("projects", ("name",), False),
    ("contracts", ("project_id", "external_key"), True),
    ("licenses", ("project_id", "external_key"), True),
    ("licenses", ("license_type",), False),
    ("licenses", ("expiry_date",), False),
    ("risks", ("project_id", "external_key"), True),
    ("risks", ("status",), False),
    ("risks", ("project_id", "status"), False),
    ("users", ("email",), True),
    ("users", ("external_subject",), False),
    ("api_keys", ("key_prefix",), False),
    ("api_keys", ("user_id",), False),
    ("project_access", ("user_id", "project_id"), True),
    ("project_access", ("project_id",), False),
    ("admin_sessions", ("session_hash",), True),
    ("admin_sessions", ("user_id",), False),
    ("audit_events", ("timestamp",), False),
    ("audit_events", ("user_id",), False),
    ("audit_events", ("tool_name",), False),
    ("audit_disclosures", ("audit_event_id",), False),
    ("audit_disclosures", ("project_id",), False),
]


def test_connect_enables_foreign_keys(tmp_path) -> None:
    conn = db.connect(tmp_path / "legal.db")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_initialize_database_creates_required_tables_and_columns(tmp_path) -> None:
    db_path = tmp_path / "legal.db"

    db.initialize_database(db_path)

    conn = db.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table'"
            )
        }
        assert set(EXPECTED_COLUMNS).issubset(tables)

        for table_name, expected_columns in EXPECTED_COLUMNS.items():
            columns = [
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table_name})")
            ]
            assert columns == expected_columns
    finally:
        conn.close()


def test_initialize_database_creates_required_indexes(tmp_path) -> None:
    db_path = tmp_path / "legal.db"
    db.initialize_database(db_path)

    conn = db.connect(db_path)
    try:
        actual_indexes = []
        for table_name in EXPECTED_COLUMNS:
            for index_row in conn.execute(f"PRAGMA index_list({table_name})"):
                index_name = index_row["name"]
                columns = tuple(
                    row["name"] for row in conn.execute(f"PRAGMA index_info({index_name})")
                )
                actual_indexes.append((table_name, columns, bool(index_row["unique"])))

        for expected in EXPECTED_INDEXES:
            assert expected in actual_indexes
    finally:
        conn.close()


def test_schema_enforces_project_identity_and_allows_duplicate_names(tmp_path) -> None:
    db_path = tmp_path / "legal.db"
    db.initialize_database(db_path)

    conn = db.connect(db_path)
    try:
        conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Same Name", "live"),
        )
        conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-002", "Same Name", "planning"),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into projects (project_code, name, stage) values (?, ?, ?)",
                ("GAME-001", "Renamed Later", "live"),
            )
    finally:
        conn.close()


def test_identity_schema_enforces_unique_email_and_project_grants(tmp_path) -> None:
    db_path = tmp_path / "legal.db"
    db.initialize_database(db_path)

    conn = db.connect(db_path)
    try:
        conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Project One", "live"),
        )
        project_id = conn.execute(
            "select id from projects where project_code = ?", ("GAME-001",)
        ).fetchone()["id"]

        conn.execute(
            "insert into users (email, display_name, role) values (?, ?, ?)",
            ("admin@example.com", "Admin User", "admin"),
        )
        user_id = conn.execute(
            "select id from users where email = ?", ("admin@example.com",)
        ).fetchone()["id"]

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into users (email, display_name, role) values (?, ?, ?)",
                ("admin@example.com", "Duplicate User", "legal"),
            )

        conn.execute(
            "insert into project_access "
            "(user_id, project_id, granted_by_user_id) values (?, ?, ?)",
            (user_id, project_id, user_id),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into project_access "
                "(user_id, project_id, granted_by_user_id) values (?, ?, ?)",
                (user_id, project_id, user_id),
            )
    finally:
        conn.close()


def test_identity_schema_enforces_required_api_key_and_grant_fields(tmp_path) -> None:
    db_path = tmp_path / "legal.db"
    db.initialize_database(db_path)

    conn = db.connect(db_path)
    try:
        conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Project One", "live"),
        )
        project_id = conn.execute(
            "select id from projects where project_code = ?", ("GAME-001",)
        ).fetchone()["id"]

        conn.execute(
            "insert into users (email, display_name, role) values (?, ?, ?)",
            ("admin@example.com", "Admin User", "admin"),
        )
        user_id = conn.execute(
            "select id from users where email = ?", ("admin@example.com",)
        ).fetchone()["id"]

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into api_keys (user_id, key_prefix, key_hash) values (?, ?, ?)",
                (user_id, "lk_test", "hashed-secret"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into project_access (user_id, project_id) values (?, ?)",
                (user_id, project_id),
            )
    finally:
        conn.close()


def test_audit_schema_enforces_required_fields_defaults_and_decisions(tmp_path) -> None:
    db_path = tmp_path / "legal.db"
    db.initialize_database(db_path)

    conn = db.connect(db_path)
    try:
        conn.execute(
            "insert into audit_events (tool_name, arguments_summary, result_status) "
            "values (?, ?, ?)",
            ("search_contracts", "{}", "success"),
        )
        audit_event_id = conn.execute("select id from audit_events").fetchone()["id"]
        response_record_count = conn.execute(
            "select response_record_count from audit_events where id = ?",
            (audit_event_id,),
        ).fetchone()["response_record_count"]
        assert response_record_count == 0

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into audit_events (tool_name, result_status) values (?, ?)",
                ("search_contracts", "success"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into audit_disclosures "
                "(audit_event_id, record_type, record_id, decision, reason) "
                "values (?, ?, ?, ?, ?)",
                (audit_event_id, "contract", 1, "maybe", "Invalid decision"),
            )

        conn.execute(
            "insert into audit_disclosures "
            "(audit_event_id, record_type, record_id, decision, reason) "
            "values (?, ?, ?, ?, ?)",
            (audit_event_id, "summary", None, "allowed", "Aggregate disclosure"),
        )
        disclosure = conn.execute(
            "select record_id from audit_disclosures where record_type = ?",
            ("summary",),
        ).fetchone()
        assert disclosure["record_id"] is None

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into audit_disclosures "
                "(audit_event_id, record_type, record_id, decision) "
                "values (?, ?, ?, ?)",
                (audit_event_id, "contract", 1, "allowed"),
            )
    finally:
        conn.close()


def test_schema_enforces_child_foreign_keys_and_unique_external_keys(tmp_path) -> None:
    db_path = tmp_path / "legal.db"
    db.initialize_database(db_path)

    conn = db.connect(db_path)
    try:
        conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Project One", "live"),
        )
        conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-002", "Project Two", "live"),
        )
        first_project_id = conn.execute(
            "select id from projects where project_code = ?", ("GAME-001",)
        ).fetchone()["id"]
        second_project_id = conn.execute(
            "select id from projects where project_code = ?", ("GAME-002",)
        ).fetchone()["id"]

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into risks (project_id, external_key, description, status) "
                "values (?, ?, ?, ?)",
                (999, "risk-1", "Missing parent", "open"),
            )

        conn.execute(
            "insert into contracts (project_id, external_key, title) values (?, ?, ?)",
            (first_project_id, "contract-1", "Publishing Agreement"),
        )
        conn.execute(
            "insert into contracts (project_id, external_key, title) values (?, ?, ?)",
            (second_project_id, "contract-1", "Another Agreement"),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into contracts (project_id, external_key, title) values (?, ?, ?)",
                (first_project_id, "contract-1", "Duplicate Agreement"),
            )
    finally:
        conn.close()
