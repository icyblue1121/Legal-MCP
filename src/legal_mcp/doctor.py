"""Install health checks for Legal-MCP."""

from __future__ import annotations

import json
import sqlite3
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

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
    remote_url: str | None = None,
) -> HealthReport:
    checks = [
        HealthCheck("package_import", True, f"legal-mcp {__version__} imports successfully")
    ]
    if remote_url:
        checks.append(_check_remote_health(remote_url))
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


def _health_url(remote_url: str) -> str:
    parsed = urlparse(remote_url)
    return urlunparse((parsed.scheme, parsed.netloc, "/healthz", "", "", ""))


def _check_remote_health(remote_url: str) -> HealthCheck:
    try:
        request = urllib.request.Request(_health_url(remote_url), method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        ok = response.status == 200 and payload.get("database") == "ready"
    except Exception as exc:
        return HealthCheck(
            "remote_http",
            False,
            f"remote HTTP server check failed: {exc}",
        )

    if ok:
        return HealthCheck("remote_http", True, f"remote HTTP server is healthy: {remote_url}")
    return HealthCheck("remote_http", False, f"remote HTTP server is unhealthy: {remote_url}")


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
