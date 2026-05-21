import json

from legal_mcp import db
from legal_mcp.tools import call_tool


def test_audit_log_records_successful_and_failed_tool_calls(tmp_path) -> None:
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        conn.execute(
            "insert into projects (project_code, name, stage) values (?, ?, ?)",
            ("GAME-001", "Project One", "live"),
        )
        conn.commit()
    finally:
        conn.close()

    call_tool(
        "list_projects",
        {"rationale": "status review", "source_client": "pytest"},
        database_path=database_path,
        audit_path=audit_path,
    )
    call_tool(
        "get_project_context",
        {"project_id_or_name": "Missing", "rationale": "status review"},
        database_path=database_path,
        audit_path=audit_path,
    )

    records = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert records[0]["tool_name"] == "list_projects"
    assert records[0]["rationale"] == "status review"
    assert records[0]["source_client"] == "pytest"
    assert records[0]["result_status"] == "success"
    assert records[0]["error_code"] is None
    assert records[1]["tool_name"] == "get_project_context"
    assert records[1]["result_status"] == "error"
    assert records[1]["error_code"] == "not_found"
    assert "Missing" in records[1]["arguments_summary"]
