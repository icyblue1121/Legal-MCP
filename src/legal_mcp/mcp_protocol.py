"""Shared JSON-RPC MCP protocol handling for Legal-MCP transports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from legal_mcp import __version__
from legal_mcp.tools import TOOL_DEFINITIONS, call_tool

PROTOCOL_VERSION = "2024-11-05"


def handle_message(
    message: dict[str, Any],
    *,
    database_path: str | Path,
    audit_path: str | Path,
) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    if request_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "legal-mcp", "version": __version__},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOL_DEFINITIONS}}
    if method == "tools/call":
        params = message.get("params") or {}
        result = call_tool(
            params.get("name", ""),
            params.get("arguments") or {},
            database_path=database_path,
            audit_path=audit_path,
        )
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, sort_keys=True),
                    }
                ],
                "isError": "error" in result,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }
