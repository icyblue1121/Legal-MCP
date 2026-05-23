from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from legal_mcp import db
from legal_mcp.http_server import build_http_server
from legal_mcp.identity import ROLE_BUSINESS, ROLE_LEGAL, create_api_key, create_user

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _database_with_project(path: Path) -> int:
    db.initialize_database(path)
    conn = db.connect(path)
    try:
        cursor = conn.execute(
            """
            insert into projects (project_code, name, stage, release_team, contact_person)
            values (?, ?, ?, ?, ?)
            """,
            ("Mgame", "失序之地", "测试中", "上海发行中心", "沪小胖"),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


@pytest.fixture
def http_service(tmp_path: Path):
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    _database_with_project(database_path)
    server = build_http_server(
        host="127.0.0.1",
        port=0,
        database_path=database_path,
        audit_path=audit_path,
        bearer_token="secret-token",
        allowed_origins=("http://legal.internal",),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post_json(url: str, body: dict, token: str = "secret-token", origin: str | None = None):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    if origin is not None:
        headers["Origin"] = origin
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with _OPENER.open(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_healthz_reports_ready(http_service) -> None:
    _, base_url = http_service

    with _OPENER.open(f"{base_url}/healthz", timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))

    assert response.status == 200
    assert payload == {"service": "legal-mcp", "database": "ready"}


def test_http_mcp_tools_call_returns_project_context(http_service) -> None:
    _, base_url = http_service

    status, payload = _post_json(
        f"{base_url}/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_project_context",
                "arguments": {
                    "project_id_or_name": "Mgame",
                    "rationale": "team query",
                    "source_client": "pytest-http",
                },
            },
        },
        origin="http://legal.internal",
    )

    tool_payload = json.loads(payload["result"]["content"][0]["text"])
    assert status == 200
    assert tool_payload["project"]["contact_person"] == "沪小胖"


def test_http_mcp_accepts_named_user_api_key_for_granted_project(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    project_id = _database_with_project(database_path)
    conn = db.connect(database_path)
    try:
        grantor = create_user(
            conn,
            email="grantor@example.com",
            display_name="Grantor",
            role=ROLE_LEGAL,
        )
        business_user = create_user(
            conn,
            email="business@example.com",
            display_name="Business User",
            role=ROLE_BUSINESS,
        )
        conn.execute(
            """
            insert into project_access (user_id, project_id, granted_by_user_id)
            values (?, ?, ?)
            """,
            (business_user["id"], project_id, grantor["id"]),
        )
        conn.commit()
        api_key = create_api_key(conn, user_id=business_user["id"], label="pytest")
    finally:
        conn.close()

    server = build_http_server(
        host="127.0.0.1",
        port=0,
        database_path=database_path,
        audit_path=audit_path,
        bearer_token="legacy-token",
        allowed_origins=("http://legal.internal",),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _post_json(
            f"http://127.0.0.1:{server.server_port}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_project_context",
                    "arguments": {
                        "project_id_or_name": "Mgame",
                        "rationale": "team query",
                        "source_client": "pytest-http",
                    },
                },
            },
            token=api_key.plaintext,
            origin="http://legal.internal",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    tool_payload = json.loads(payload["result"]["content"][0]["text"])
    assert status == 200
    assert tool_payload["project"]["project_code"] == "Mgame"


def test_http_mcp_rejects_missing_token(http_service) -> None:
    _, base_url = http_service
    request = urllib.request.Request(
        f"{base_url}/mcp",
        data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with pytest.raises(urllib.error.HTTPError) as exc:
        _OPENER.open(request, timeout=5)

    assert exc.value.code == 401


def test_http_mcp_rejects_disallowed_origin(http_service) -> None:
    _, base_url = http_service

    with pytest.raises(urllib.error.HTTPError) as exc:
        _post_json(
            f"{base_url}/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            origin="http://evil.example",
        )

    assert exc.value.code == 403


def test_http_mcp_allows_absent_origin_for_non_browser_clients(http_service) -> None:
    _, base_url = http_service

    status, payload = _post_json(
        f"{base_url}/mcp",
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )

    assert status == 200
    assert payload["result"]["tools"][0]["name"] == "list_projects"
