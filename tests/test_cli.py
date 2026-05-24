import sqlite3

from legal_mcp import __version__
from legal_mcp.cli import main
from legal_mcp.identity import verify_password


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


def test_serve_parses_update_check_url() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(
        [
            "serve",
            "--update-check-url",
            "https://updates.example/legal-mcp.json",
        ]
    )

    assert args.update_check_url == "https://updates.example/legal-mcp.json"


def test_serve_parses_agent_public_only() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(["serve", "--agent-public-only"])

    assert args.agent_public_only is True


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


def test_serve_http_parses_agent_public_only() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(["serve-http", "--token", "secret", "--agent-public-only"])

    assert args.agent_public_only is True


def test_serve_http_parses_update_check_url() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(
        [
            "serve-http",
            "--token",
            "secret",
            "--update-check-url",
            "https://updates.example/legal-mcp.json",
        ]
    )

    assert args.update_check_url == "https://updates.example/legal-mcp.json"


def test_admin_create_user_parser() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(
        [
            "admin",
            "create-user",
            "--email",
            "admin@example.com",
            "--display-name",
            "Admin User",
            "--role",
            "admin",
            "--password",
            "secret",
        ]
    )

    assert args.command == "admin"
    assert args.admin_command == "create-user"
    assert args.email == "admin@example.com"
    assert args.role == "admin"


def test_admin_without_subcommand_fails(capsys) -> None:
    parser = main.__globals__["build_parser"]()

    try:
        parser.parse_args(["admin"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected admin without subcommand to fail")

    captured = capsys.readouterr()
    assert "required" in captured.err


def test_admin_create_user_requires_password_for_admin(tmp_path, capsys) -> None:
    database_path = tmp_path / "legal.db"

    assert (
        main(
            [
                "admin",
                "create-user",
                "--email",
                "admin@example.com",
                "--display-name",
                "Admin User",
                "--role",
                "admin",
                "--db",
                str(database_path),
            ]
        )
        != 0
    )

    captured = capsys.readouterr()
    assert "--password is required" in captured.err
    assert not database_path.exists()


def test_admin_create_user_duplicate_returns_clean_error(tmp_path, capsys) -> None:
    database_path = tmp_path / "legal.db"
    command = [
        "admin",
        "create-user",
        "--email",
        "admin@example.com",
        "--display-name",
        "Admin User",
        "--role",
        "admin",
        "--password",
        "secret",
        "--db",
        str(database_path),
    ]

    assert main(command) == 0
    capsys.readouterr()

    assert main(command) != 0
    captured = capsys.readouterr()
    assert "user already exists: admin@example.com" in captured.err
    assert "IntegrityError" not in captured.err
    assert "Traceback" not in captured.err


def test_admin_create_user_writes_admin_password_hash(tmp_path, capsys) -> None:
    database_path = tmp_path / "legal.db"

    assert (
        main(
            [
                "admin",
                "create-user",
                "--email",
                "admin@example.com",
                "--display-name",
                "Admin User",
                "--role",
                "admin",
                "--password",
                "correct horse battery staple",
                "--db",
                str(database_path),
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert "Created user admin@example.com (admin)" in captured.out

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        user = conn.execute(
            "select role, password_hash from users where email = ?",
            ("admin@example.com",),
        ).fetchone()
    finally:
        conn.close()

    assert user is not None
    assert user["role"] == "admin"
    assert user["password_hash"] is not None
    assert verify_password("correct horse battery staple", user["password_hash"]) is True


def test_serve_admin_parser() -> None:
    parser = main.__globals__["build_parser"]()

    args = parser.parse_args(["serve-admin", "--host", "0.0.0.0", "--port", "8766"])

    assert args.command == "serve-admin"
    assert args.host == "0.0.0.0"
    assert args.port == 8766


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

    for client in ["claude", "claude-code", "windsurf", "vscode"]:
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
