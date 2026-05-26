"""Configurable server-side AI provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from legal_mcp.agent_config import AgentConfig


@dataclass(frozen=True)
class AIMessage:
    role: str
    content: str


class AIProvider(Protocol):
    def complete(self, messages: list[AIMessage]) -> AIMessage:
        """Return one assistant message for the provided sanitized prompt."""


class NoopAIProvider:
    def complete(self, messages: list[AIMessage]) -> AIMessage:
        return AIMessage(role="assistant", content="{}")


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def complete(self, messages: list[AIMessage]) -> AIMessage:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for openai-compatible AI") from exc

        # temperature=0 for deterministic plans; response_format json_object asks
        # OpenAI-compatible providers (incl. DeepSeek) for a bare JSON object so
        # the planner does not have to parse prose or markdown fences.
        chat = ChatOpenAI(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        response = chat.invoke(
            [{"role": message.role, "content": message.content} for message in messages]
        )
        return AIMessage(role="assistant", content=_strip_code_fence(str(response.content)))


def _strip_code_fence(content: str) -> str:
    """Remove a surrounding markdown code fence if the model added one."""
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def provider_from_config(config: AgentConfig) -> AIProvider | None:
    if not config.ai_api_key:
        return None
    if config.ai_provider != "openai_compatible":
        return None
    return OpenAICompatibleProvider(
        api_key=config.ai_api_key,
        model=config.ai_model,
        base_url=config.ai_base_url,
    )


def build_ai_provider(config: AgentConfig) -> AIProvider:
    if config.ai_provider == "none" or not config.ai_api_key:
        return NoopAIProvider()
    if config.ai_provider == "openai_compatible":
        return OpenAICompatibleProvider(
            api_key=config.ai_api_key,
            model=config.ai_model,
            base_url=config.ai_base_url,
        )
    raise ValueError(f"unsupported AI provider: {config.ai_provider}")
