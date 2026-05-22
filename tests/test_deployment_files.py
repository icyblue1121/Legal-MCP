from pathlib import Path


def test_dockerfile_runs_http_server() -> None:
    content = Path("Dockerfile").read_text()

    assert "FROM python:3.11-slim" in content
    assert "legal-mcp" in content
    assert "serve-http" in content
    assert "LEGAL_MCP_TOKEN" in content


def test_compose_mounts_data_and_sets_http_command() -> None:
    content = Path("docker-compose.yml").read_text()

    assert "legal-mcp:" in content
    assert "8765:8765" in content
    assert "./data:/data" in content
    assert "LEGAL_MCP_TOKEN" in content
    assert "serve-http" in content
