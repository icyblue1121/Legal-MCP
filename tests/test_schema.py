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
