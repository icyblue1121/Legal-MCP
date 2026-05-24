from __future__ import annotations

from legal_mcp.agent_config import AgentConfig, load_agent_config


def test_load_agent_config_defaults_to_disabled_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LEGAL_MCP_AGENT_MODEL", raising=False)

    config = load_agent_config()

    assert config.enabled is False
    assert config.model == "gpt-4.1-mini"


def test_load_agent_config_reads_openai_compatible_settings(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:4000/v1")
    monkeypatch.setenv("LEGAL_MCP_AGENT_MODEL", "local-router")
    monkeypatch.setenv("LEGAL_MCP_AGENT_PUBLIC_ONLY", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000")

    config = load_agent_config()

    assert config == AgentConfig(
        enabled=True,
        model="local-router",
        openai_base_url="http://localhost:4000/v1",
        public_agent_only=True,
        langfuse_enabled=True,
        langfuse_base_url="http://127.0.0.1:3000",
    )
