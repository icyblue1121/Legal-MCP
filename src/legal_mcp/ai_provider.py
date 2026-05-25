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

        chat = ChatOpenAI(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
        )
        response = chat.invoke(
            [{"role": message.role, "content": message.content} for message in messages]
        )
        return AIMessage(role="assistant", content=str(response.content))


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
