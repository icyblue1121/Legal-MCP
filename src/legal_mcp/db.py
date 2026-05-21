"""SQLite database helpers for Legal-MCP."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path
from typing import TypeAlias

DatabasePath: TypeAlias = str | Path


def connect(database_path: DatabasePath) -> sqlite3.Connection:
    """Open a SQLite connection with project-required defaults."""
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Apply the canonical SQLite schema to an open connection."""
    conn.execute("PRAGMA foreign_keys = ON")
    schema_sql = (
        resources.files("legal_mcp")
        .joinpath("schema.sql")
        .read_text(encoding="utf-8")
    )
    conn.executescript(schema_sql)
    conn.commit()


def initialize_database(database_path: DatabasePath) -> None:
    """Create or update a database file with the canonical schema."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = connect(path)
    try:
        initialize_schema(conn)
    finally:
        conn.close()
