"""Command-line interface for Legal-MCP."""

from __future__ import annotations

import argparse
from pathlib import Path

from legal_mcp import __version__
from legal_mcp.import_pipeline import import_file


DEFAULT_DATABASE_PATH = Path.home() / ".legal-mcp" / "legal.db"


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "import":
        report = import_file(args.path, database_path=args.db)
        _print_import_report(report)
        return 1 if report.errors else 0

    parser.print_help()
    return 0


def _print_import_report(report) -> None:
    print("Import complete")
    for entity, counts in report.counts.items():
        if any(counts.values()):
            print(
                f"{entity}: "
                f"created={counts['created']} "
                f"updated={counts['updated']} "
                f"skipped={counts['skipped']} "
                f"failed={counts['failed']}"
            )
    if report.warnings:
        print(f"warnings={len(report.warnings)}")
    if report.errors:
        print(f"errors={len(report.errors)}")
