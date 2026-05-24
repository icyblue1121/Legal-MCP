from __future__ import annotations

from legal_mcp.agent_observability import build_trace_metadata, langfuse_callbacks


def test_langfuse_callbacks_empty_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert langfuse_callbacks() == []


def test_langfuse_callbacks_require_local_base_url(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)

    assert langfuse_callbacks() == []


def test_build_trace_metadata_excludes_raw_tool_result() -> None:
    metadata = build_trace_metadata(
        thread_id="thread-1",
        tool_name="get_project_fields",
        status="success",
        result={"project": {"website": "https://sensitive.example"}},
    )

    assert metadata["thread_id"] == "thread-1"
    assert metadata["tool_name"] == "get_project_fields"
    assert metadata["status"] == "success"
    assert "result" not in metadata
