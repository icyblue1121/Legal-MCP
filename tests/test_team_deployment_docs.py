from pathlib import Path


def test_readme_documents_team_deployment() -> None:
    content = Path("README.md").read_text()

    assert "Team Deployment" in content
    assert "legal-mcp serve-http" in content
    assert "legal-mcp proxy" in content


def test_readme_keeps_deployment_notes_outside_git() -> None:
    content = Path("README.md").read_text()

    assert "Keep deployment notes" in content
    assert "outside Git" in content


def test_team_deployment_docs_describe_v13_minimum_disclosure() -> None:
    content = Path("Docs/team-deployment.md").read_text(encoding="utf-8")

    assert "1.3" in content
    assert "minimum disclosure" in content
    assert "get_project_context" in content
    assert "startup checks" in content
