"""Command-line interface for Legal-MCP."""

from __future__ import annotations

import argparse

from legal_mcp import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="legal-mcp")
    parser.add_argument(
        "--version",
        action="version",
        version=f"legal-mcp {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
