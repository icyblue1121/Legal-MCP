"""Install health checks for Legal-MCP."""

from __future__ import annotations

import json
import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path

from legal_mcp import __version__, db
from legal_mcp.cli import DEFAULT_DATABASE_PATH

REQUIRED_TABLES = {"projects", "licenses", "contracts", "risks"}


@dataclass(frozen=True)
class HealthCheck:
    code: str
    ok: bool
    message: str


@dataclass(frozen=True)
class HealthReport:
    checks: list[HealthCheck]

    @property
    def healthy(self) -> bool:
        return all(check.ok for check in self.checks)


def check_install_health(
    *,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    config_path: str | Path | None = None,
) -> HealthReport:
    checks = [
        HealthCheck("package_import", True, f"legal-mcp {__version__} imports successfully")
    ]
    database = Path(database_path)
    if not database.exists():
        checks.append(HealthCheck("database_missing", False, f"database not found: {database}"))
    else:
        checks.extend(_check_database(database))

    if config_path is not None:
        config = Path(config_path)
        config_exists = config.exists()
        checks.append(
            HealthCheck(
                "config_exists",
                config_exists,
                f"client config {'found' if config_exists else 'not found'}: {config}",
            )
        )
        if config_exists:
            checks.append(_check_config(config))
    return HealthReport(checks)


def _check_database(database_path: Path) -> list[HealthCheck]:
    try:
        conn = db.connect(database_path)
        try:
            rows = conn.execute("select name from sqlite_master where type = 'table'").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return [
            HealthCheck(
                "database_readable",
                False,
                f"database could not be read: {exc}",
            )
        ]
    tables = {row["name"] for row in rows}
    missing_tables = sorted(REQUIRED_TABLES - tables)
    if missing_tables:
        return [
            HealthCheck(
                "database_schema",
                False,
                f"database schema is missing tables: {', '.join(missing_tables)}",
            )
        ]
    return [HealthCheck("database_schema", True, f"database schema is ready: {database_path}")]


def _check_config(config_path: Path) -> HealthCheck:
    try:
        if config_path.suffix == ".toml":
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            present = "legal-mcp" in config.get("mcp_servers", {})
        else:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            present = (
                "legal-mcp" in config.get("mcpServers", {})
                or "legal-mcp" in config.get("servers", {})
                or "legal-mcp" in config
            )
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        return HealthCheck("config_readable", False, f"client config could not be read: {exc}")

    return HealthCheck(
        "config_legal_mcp",
        present,
        "client config includes legal-mcp server"
        if present
        else "client config does not include legal-mcp server",
    )
