"""Fine-grained contract MCP tools."""

from __future__ import annotations

import sqlite3
from typing import Any

from legal_mcp.policy import AccessContext, project_is_visible
from legal_mcp.tool_catalog import CONTRACT_FIELDS

CONTRACT_IDENTITY_FIELDS = ("contract_number", "title")


def get_contract_fields(
    conn: sqlite3.Connection,
    arguments: dict[str, Any],
    access_context: AccessContext | None,
) -> dict[str, Any]:
    contract_number = arguments.get("contract_number")
    fields = arguments.get("fields")
    if not isinstance(contract_number, str) or not contract_number.strip():
        return _error("validation_error", "contract_number is required")
    if not isinstance(fields, list) or not fields:
        return _error("validation_error", "fields is required")
    requested = {field for field in fields if isinstance(field, str)}
    if len(requested) != len(fields) or not requested.issubset(set(CONTRACT_FIELDS)):
        return _error("validation_error", "fields must contain known contract field names")

    row = conn.execute(
        "select * from contracts where contract_number = ? or external_key = ?",
        (contract_number, contract_number),
    ).fetchone()
    if row is None:
        return _error("not_found", "contract not found")
    if not project_is_visible(conn, access_context, int(row["project_id"])):
        return _error("not_found", "contract not found")

    projected = [*CONTRACT_IDENTITY_FIELDS, *sorted(requested)]
    return {
        "contract": {
            field: row[field]
            for field in projected
            if field in row.keys()
        }
    }


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "candidates": [], "details": {}}}
