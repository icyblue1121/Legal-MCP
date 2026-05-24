from __future__ import annotations

import json
from pathlib import Path

from legal_mcp import db
from legal_mcp.identity import ROLE_BUSINESS, create_user
from legal_mcp.mcp_protocol import handle_message
from legal_mcp.policy import AccessContext


def _database_with_project(path: Path) -> None:
    db.initialize_database(path)
    conn = db.connect(path)
    try:
        conn.execute(
            """
            insert into projects (
              project_code, name, stage, legal_bp, department,
              release_team, contact_person, website, notes
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Mgame",
                "失序之地",
                "预计 2026 年 12月做PC端测试",
                "张三",
                "MGAME项目部",
                "上海发行中心",
                "沪小胖",
                "www.mgame.com",
                "Steam 发行",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_handle_initialize_returns_server_capabilities(tmp_path: Path) -> None:
    response = handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        database_path=tmp_path / "legal.db",
        audit_path=tmp_path / "audit.jsonl",
    )

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "legal-mcp"
    assert response["result"]["capabilities"] == {"tools": {}}


def test_handle_tools_list_returns_legal_mcp_tools(tmp_path: Path) -> None:
    response = handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        database_path=tmp_path / "legal.db",
        audit_path=tmp_path / "audit.jsonl",
    )

    names = [tool["name"] for tool in response["result"]["tools"]]
    assert "resolve_project" in names
    assert "get_project_fields" in names
    assert "list_project_contracts" in names
    assert "get_project_context" not in names
    get_project_fields = next(
        tool for tool in response["result"]["tools"] if tool["name"] == "get_project_fields"
    )
    fields_schema = get_project_fields["inputSchema"]["properties"]["fields"]
    assert fields_schema["type"] == "array"
    assert "website" in fields_schema["items"]["enum"]


def test_handle_tool_call_returns_json_text_content(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    _database_with_project(database_path)

    response = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "get_project_fields",
                    "arguments": {
                        "project_id_or_name": "Mgame",
                        "fields": ["contact_person"],
                        "rationale": "team deployment smoke test",
                        "source_client": "pytest",
                    },
            },
        },
        database_path=database_path,
        audit_path=audit_path,
    )

    content = response["result"]["content"]
    payload = json.loads(content[0]["text"])
    assert response["id"] == 3
    assert response["result"]["isError"] is False
    assert payload["project"]["contact_person"] == "沪小胖"
    assert audit_path.exists()


def test_handle_tool_call_uses_access_context_to_hide_ungranted_project(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    _database_with_project(database_path)
    conn = db.connect(database_path)
    try:
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
    finally:
        conn.close()

    response = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "get_project_fields",
                    "arguments": {
                        "project_id_or_name": "Mgame",
                        "fields": ["contact_person"],
                        "rationale": "team deployment smoke test",
                        "source_client": "pytest",
                    },
            },
        },
        database_path=database_path,
        audit_path=audit_path,
        access_context=AccessContext.from_user(business_user),
    )

    payload = json.loads(response["result"]["content"][0]["text"])
    assert response["result"]["isError"] is True
    assert payload["error"]["code"] == "not_found"


def test_handle_notification_returns_none(tmp_path: Path) -> None:
    response = handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        database_path=tmp_path / "legal.db",
        audit_path=tmp_path / "audit.jsonl",
    )

    assert response is None
