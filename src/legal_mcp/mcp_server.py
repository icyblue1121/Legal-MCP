"""Minimal stdio MCP server for Legal-MCP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import BinaryIO, TextIO

from legal_mcp.audit import DEFAULT_AUDIT_PATH
from legal_mcp.cli import DEFAULT_DATABASE_PATH
from legal_mcp.mcp_protocol import handle_message


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
        response = handle_message(message, database_path=database_path, audit_path=audit_path)
        if response is not None:
            _write_message(stdout, response)
            stdout.flush()


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
