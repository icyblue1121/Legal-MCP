"""Minimal stdio MCP server for Legal-MCP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import BinaryIO, TextIO

from legal_mcp.audit import DEFAULT_AUDIT_PATH
from legal_mcp.cli import DEFAULT_DATABASE_PATH
from legal_mcp.tools import TOOL_DEFINITIONS, call_tool

PROTOCOL_VERSION = "2024-11-05"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="legal-mcp serve")
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    serve(args.db, args.audit_log, sys.stdin.buffer, sys.stdout.buffer, sys.stderr)
    return 0


def serve(
    database_path: str | Path,
    audit_path: str | Path,
    stdin: BinaryIO,
    stdout: BinaryIO,
    stderr: TextIO,
) -> None:
    while True:
        message = _read_message(stdin)
        if message is None:
            return
        response = _handle_message(message, database_path=database_path, audit_path=audit_path)
        if response is not None:
            _write_message(stdout, response)
            stdout.flush()


def _handle_message(
    message: dict,
    *,
    database_path: str | Path,
    audit_path: str | Path,
) -> dict | None:
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
                "serverInfo": {"name": "legal-mcp", "version": "0.1.0"},
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


def _read_message(stdin: BinaryIO) -> dict | None:
    headers = {}
    while True:
        line = stdin.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            break
        name, value = line.decode("ascii").strip().split(":", 1)
        headers[name.lower()] = value.strip()

    content_length = int(headers["content-length"])
    body = stdin.read(content_length)
    if not body:
        return None
    return json.loads(body)


def _write_message(stdout: BinaryIO, message: dict) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stdout.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)


if __name__ == "__main__":
    raise SystemExit(main())
