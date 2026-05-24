from __future__ import annotations

import os
from typing import Any


def langfuse_callbacks() -> list[Any]:
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return []
    if not os.environ.get("LANGFUSE_BASE_URL"):
        return []

    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]


def build_trace_metadata(
    *,
    thread_id: str,
    tool_name: str | None,
    status: str,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "thread_id": thread_id,
        "tool_name": tool_name,
        "status": status,
    }
    if result and isinstance(result.get("error"), dict):
        metadata["error_code"] = result["error"].get("code")
    return metadata
