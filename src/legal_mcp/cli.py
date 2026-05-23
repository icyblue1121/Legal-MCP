"""Command-line interface for Legal-MCP."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from legal_mcp import __version__
from legal_mcp.audit import DEFAULT_AUDIT_PATH
from legal_mcp.import_pipeline import import_file


DEFAULT_DATABASE_PATH = Path.home() / ".legal-mcp" / "legal.db"
SETUP_CLIENTS = ("claude", "claude-code", "cursor", "windsurf", "vscode", "codex", "generic")
ADMIN_ROLES = ("admin", "legal", "business", "auditor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="legal-mcp")
    parser.add_argument(
        "--version",
        action="version",
        version=f"legal-mcp {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    import_parser = subparsers.add_parser("import", help="Import CSV/XLSX data")
    import_parser.add_argument("path", type=Path)
    import_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    serve_parser = subparsers.add_parser("serve", help="Run the stdio MCP server")
    serve_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    serve_parser.add_argument(
        "--audit-log",
        type=Path,
        default=DEFAULT_AUDIT_PATH,
        help="Audit log JSONL path",
    )
    serve_http_parser = subparsers.add_parser("serve-http", help="Run the HTTP MCP server")
    serve_http_parser.add_argument("--host", default="127.0.0.1")
    serve_http_parser.add_argument("--port", type=int, default=8765)
    serve_http_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    serve_http_parser.add_argument(
        "--audit-log",
        type=Path,
        default=DEFAULT_AUDIT_PATH,
        help="Audit log JSONL path",
    )
    serve_http_parser.add_argument("--token", required=True, help="Bearer token required by clients")
    serve_http_parser.add_argument(
        "--allow-origin",
        dest="allowed_origins",
        action="append",
        default=[],
        help="Allowed browser Origin. Repeat for multiple origins.",
    )
    serve_admin_parser = subparsers.add_parser("serve-admin", help="Run the admin web server")
    serve_admin_parser.add_argument("--host", default="127.0.0.1")
    serve_admin_parser.add_argument("--port", type=int, default=8766)
    serve_admin_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    admin_parser = subparsers.add_parser("admin", help="Admin bootstrap commands")
    admin_subparsers = admin_parser.add_subparsers(dest="admin_command", required=True)
    create_user_parser = admin_subparsers.add_parser("create-user", help="Create a local user")
    create_user_parser.add_argument("--email", required=True)
    create_user_parser.add_argument("--display-name", required=True)
    create_user_parser.add_argument("--role", choices=ADMIN_ROLES, required=True)
    create_user_parser.add_argument("--password")
    create_user_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    proxy_parser = subparsers.add_parser("proxy", help="Proxy local stdio MCP to a remote HTTP MCP server")
    proxy_parser.add_argument("--url", required=True, help="Remote HTTP MCP endpoint URL")
    proxy_parser.add_argument("--token", required=True, help="Bearer token for remote HTTP MCP server")
    proxy_parser.add_argument("--timeout", type=float, default=30)
    setup_parser = subparsers.add_parser("setup", help="Configure a local MCP client")
    setup_parser.add_argument(
        "--client",
        choices=SETUP_CLIENTS,
        help="Client configuration to write",
    )
    setup_parser.add_argument("--config", type=Path, help="Override client config path")
    setup_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    setup_parser.add_argument(
        "--audit-log",
        type=Path,
        default=DEFAULT_AUDIT_PATH,
        help=f"Audit log path (default: {DEFAULT_AUDIT_PATH})",
    )
    setup_parser.add_argument(
        "--command",
        dest="server_command",
        default="legal-mcp",
        help="Command clients should run to start Legal-MCP",
    )
    setup_parser.add_argument("--remote-url", help="Remote HTTP MCP endpoint for team proxy mode")
    setup_parser.add_argument("--token", help="Bearer token for remote HTTP MCP endpoint")
    doctor_parser = subparsers.add_parser("doctor", help="Validate local install health")
    doctor_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    doctor_parser.add_argument("--config", type=Path, help="Optional client config path to check")
    doctor_parser.add_argument("--remote-url", help="Remote HTTP MCP endpoint to check")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "import":
        report = import_file(args.path, database_path=args.db)
        _print_import_report(report)
        return 1 if report.errors else 0
    if args.command == "serve":
        from legal_mcp.mcp_server import serve

        serve(args.db, args.audit_log, sys.stdin.buffer, sys.stdout.buffer, sys.stderr)
        return 0
    if args.command == "serve-http":
        from legal_mcp.http_server import serve_http

        serve_http(
            host=args.host,
            port=args.port,
            database_path=args.db,
            audit_path=args.audit_log,
            bearer_token=args.token,
            allowed_origins=tuple(args.allowed_origins),
        )
        return 0
    if args.command == "serve-admin":
        from legal_mcp.admin_server import build_admin_server

        server = build_admin_server(host=args.host, port=args.port, database_path=args.db)
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return 0
    if args.command == "admin" and args.admin_command == "create-user":
        from legal_mcp import db
        from legal_mcp.identity import create_user, hash_password

        if args.role == "admin" and not args.password:
            print("Error: --password is required when creating an admin user", file=sys.stderr)
            return 2

        db.initialize_database(args.db)
        conn = db.connect(args.db)
        try:
            try:
                create_user(
                    conn,
                    email=args.email,
                    display_name=args.display_name,
                    role=args.role,
                    password_hash=hash_password(args.password) if args.password else None,
                )
            except sqlite3.IntegrityError:
                print(f"Error: user already exists: {args.email}", file=sys.stderr)
                return 1
        finally:
            conn.close()
        print(f"Created user {args.email} ({args.role})")
        return 0
    if args.command == "proxy":
        from legal_mcp.proxy import proxy_stdio

        proxy_stdio(url=args.url, token=args.token, timeout=args.timeout)
        return 0
    if args.command == "setup":
        from legal_mcp.setup_wizard import configure_client

        client = args.client or _prompt_setup_client()
        config_path = configure_client(
            client,
            config_path=args.config,
            database_path=args.db,
            audit_path=args.audit_log,
            command=args.server_command,
            remote_url=args.remote_url,
            token=args.token,
        )
        print(f"Configured {client}: {config_path}")
        print(f"Database ready: {args.db}")
        print("You can re-run legal-mcp setup at any time to repair or update this configuration.")
        return 0
    if args.command == "doctor":
        from legal_mcp.doctor import check_install_health

        report = check_install_health(
            database_path=args.db,
            config_path=args.config,
            remote_url=args.remote_url,
        )
        status = "healthy" if report.healthy else "unhealthy"
        print(f"Legal-MCP doctor: {status}")
        for check in report.checks:
            mark = "ok" if check.ok else "fail"
            print(f"{mark}: {check.message}")
        return 0 if report.healthy else 1

    parser.print_help()
    return 0


def _prompt_setup_client() -> str:
    print("Choose an MCP client to configure:")
    for index, client in enumerate(SETUP_CLIENTS, start=1):
        print(f"  {index}. {client}")
    while True:
        answer = input("Client [cursor]: ").strip().lower()
        if not answer:
            return "cursor"
        if answer in SETUP_CLIENTS:
            return answer
        if answer.isdigit():
            selected = int(answer)
            if 1 <= selected <= len(SETUP_CLIENTS):
                return SETUP_CLIENTS[selected - 1]
        print("Please enter a client name or number.")


def _print_import_report(report) -> None:
    print(f"Import complete: {report.source_rows} source rows processed")
    for entity, counts in report.counts.items():
        if any(counts.values()):
            print(
                f"{entity}: "
                f"{counts['created']} created, "
                f"{counts['updated']} updated, "
                f"{counts['skipped']} skipped, "
                f"{counts['failed']} failed"
            )
    if report.warnings:
        print("Warnings:")
        for warning in report.warnings:
            print(
                f"- {warning.file_name} row {warning.row_number} "
                f"field {warning.field_name}: {warning.error_code} - {warning.message}"
            )
    if report.errors:
        print("Errors:")
        for error in report.errors:
            print(
                f"- {error.file_name} row {error.row_number} "
                f"field {error.field_name}: {error.error_code} - {error.message}"
            )
