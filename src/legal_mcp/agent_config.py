from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    enabled: bool
    model: str
    openai_base_url: str | None = None
    public_agent_only: bool = False
    langfuse_enabled: bool = False
    langfuse_base_url: str | None = None


def load_agent_config() -> AgentConfig:
    api_key = os.environ.get("OPENAI_API_KEY")
    return AgentConfig(
        enabled=bool(api_key),
        model=os.environ.get("LEGAL_MCP_AGENT_MODEL", "gpt-4.1-mini"),
        openai_base_url=os.environ.get("OPENAI_BASE_URL"),
        public_agent_only=_truthy(os.environ.get("LEGAL_MCP_AGENT_PUBLIC_ONLY")),
        langfuse_enabled=bool(
            os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
        ),
        langfuse_base_url=os.environ.get("LANGFUSE_BASE_URL"),
    )


def _truthy(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true", "yes", "on"}
