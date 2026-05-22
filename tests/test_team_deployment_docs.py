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
