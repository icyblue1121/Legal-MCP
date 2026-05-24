from __future__ import annotations

from pathlib import Path

from legal_mcp import db
from legal_mcp.agent_graph import run_agent_query


def _database_with_project(path: Path) -> None:
    db.initialize_database(path)
    conn = db.connect(path)
    try:
        conn.execute(
            "insert into projects (project_code, name, stage, website) values (?, ?, ?, ?)",
            ("MGAME", "失序之地", "测试中", "https://example.test"),
        )
        conn.commit()
    finally:
        conn.close()


def test_run_agent_query_returns_answer_and_persists_run(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    checkpoint_path = tmp_path / "agent-checkpoints.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    _database_with_project(database_path)

    result = run_agent_query(
        question="MGAME 的官网是什么？",
        database_path=database_path,
        checkpoint_path=checkpoint_path,
        audit_path=audit_path,
        thread_id="pytest-thread",
    )

    assert result["thread_id"] == "pytest-thread"
    assert "https://example.test" in result["answer"]
    assert result["tool_calls"][0]["tool_name"] == "get_project_fields"
    assert checkpoint_path.exists()

    conn = db.connect(database_path)
    try:
        row = conn.execute(
            "select thread_id, status, selected_tool from agent_runs"
        ).fetchone()
    finally:
        conn.close()
    assert row["thread_id"] == "pytest-thread"
    assert row["status"] == "success"
    assert row["selected_tool"] == "get_project_fields"
