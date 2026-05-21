"""Command-line interface for Legal-MCP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from legal_mcp import __version__
from legal_mcp.audit import DEFAULT_AUDIT_PATH
from legal_mcp.import_pipeline import import_file


DEFAULT_DATABASE_PATH = Path.home() / ".legal-mcp" / "legal.db"
SETUP_CLIENTS = ("claude", "cursor", "windsurf", "vscode", "codex", "generic")


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
    doctor_parser = subparsers.add_parser("doctor", help="Validate local install health")
    doctor_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    doctor_parser.add_argument("--config", type=Path, help="Optional client config path to check")
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
    if args.command == "setup":
        from legal_mcp.setup_wizard import configure_client

        client = args.client or _prompt_setup_client()
        config_path = configure_client(
            client,
            config_path=args.config,
            database_path=args.db,
            audit_path=args.audit_log,
            command=args.server_command,
        )
        print(f"Configured {client}: {config_path}")
        print(f"Database ready: {args.db}")
        print("You can re-run legal-mcp setup at any time to repair or update this configuration.")
        return 0
    if args.command == "doctor":
        from legal_mcp.doctor import check_install_health

        report = check_install_health(database_path=args.db, config_path=args.config)
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
