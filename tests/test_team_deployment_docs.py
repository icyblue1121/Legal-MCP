from pathlib import Path


def test_readme_documents_team_deployment() -> None:
    content = Path("README.md").read_text()

    assert "Team Deployment" in content
    assert "legal-mcp serve-http" in content
    assert "legal-mcp proxy" in content


def test_team_deployment_runbook_has_operator_and_member_steps() -> None:
    content = Path("Docs/team-deployment.md").read_text()

    assert "Operator setup" in content
    assert "Team member setup" in content
    assert "LEGAL_MCP_TOKEN" in content
    assert "docker compose up" in content
    assert "legal-mcp setup --client codex --remote-url" in content


def test_client_setup_mentions_remote_proxy_mode() -> None:
    content = Path("Docs/client-setup.md").read_text()

    assert "Remote proxy mode" in content
    assert "legal-mcp proxy" in content
