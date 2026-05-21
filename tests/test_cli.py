from legal_mcp import __version__
from legal_mcp.cli import main


def test_version_constant_exists() -> None:
    assert __version__ == "0.1.0"


def test_empty_cli_invocation_prints_help(capsys) -> None:
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "usage: legal-mcp" in captured.out


def test_cli_exposes_serve_command() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(["serve", "--db", "legal.db"])

    assert args.command == "serve"
