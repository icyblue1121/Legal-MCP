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


def test_cli_accepts_serve_http_options() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(
        [
            "serve-http",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--token",
            "secret-token",
            "--allow-origin",
            "http://legal.internal",
        ]
    )

    assert args.command == "serve-http"
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.token == "secret-token"
    assert args.allowed_origins == ["http://legal.internal"]


def test_cli_accepts_proxy_options() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(
        [
            "proxy",
            "--url",
            "http://legal.internal:8765/mcp",
            "--token",
            "secret-token",
        ]
    )

    assert args.command == "proxy"
    assert args.url == "http://legal.internal:8765/mcp"
    assert args.token == "secret-token"


def test_cli_setup_accepts_common_ai_app_clients() -> None:
    parser = main.__globals__["build_parser"]()

    for client in ["claude", "windsurf", "vscode"]:
        args = parser.parse_args(["setup", "--client", client])
        assert args.client == client


def test_cli_setup_can_launch_guided_mode_without_client() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(["setup"])

    assert args.command == "setup"
    assert args.client is None


def test_cli_setup_accepts_remote_proxy_options() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(
        [
            "setup",
            "--client",
            "codex",
            "--remote-url",
            "http://legal.internal:8765/mcp",
            "--token",
            "secret-token",
        ]
    )

    assert args.remote_url == "http://legal.internal:8765/mcp"
    assert args.token == "secret-token"


def test_cli_doctor_accepts_remote_url() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(["doctor", "--remote-url", "http://legal.internal:8765/mcp"])

    assert args.remote_url == "http://legal.internal:8765/mcp"


def test_setup_command_writes_cursor_config_and_mentions_rerun(tmp_path, capsys) -> None:
    config_path = tmp_path / "mcp.json"
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"

    assert (
        main(
            [
                "setup",
                "--client",
                "cursor",
                "--config",
                str(config_path),
                "--db",
                str(database_path),
                "--audit-log",
                str(audit_path),
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert "Configured cursor" in captured.out
    assert "You can re-run legal-mcp setup" in captured.out
    assert config_path.exists()
    assert database_path.exists()


def test_doctor_command_validates_setup_health(tmp_path, capsys) -> None:
    config_path = tmp_path / "mcp.json"
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    main(
        [
            "setup",
            "--client",
            "cursor",
            "--config",
            str(config_path),
            "--db",
            str(database_path),
            "--audit-log",
            str(audit_path),
        ]
    )
    capsys.readouterr()

    assert main(["doctor", "--db", str(database_path), "--config", str(config_path)]) == 0

    captured = capsys.readouterr()
    assert "Legal-MCP doctor: healthy" in captured.out
