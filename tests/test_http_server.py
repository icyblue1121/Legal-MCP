from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from legal_mcp import db
from legal_mcp import http_server as http_server_module
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


def _http_error_payload(exc: urllib.error.HTTPError) -> dict:
    return json.loads(exc.read().decode("utf-8"))


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
                "name": "get_project_fields",
                "arguments": {
                    "project_id_or_name": "Mgame",
                    "fields": ["contact_person"],
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
                    "name": "get_project_fields",
                    "arguments": {
                        "project_id_or_name": "Mgame",
                        "fields": ["project_code"],
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


def test_http_mcp_rejects_named_key_disallowed_origin_without_updating_last_used_at(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    _database_with_project(database_path)
    conn = db.connect(database_path)
    try:
        user = create_user(
            conn,
            email="business-origin@example.com",
            display_name="Business Origin",
            role=ROLE_BUSINESS,
        )
        api_key = create_api_key(conn, user_id=user["id"], label="pytest")
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post_json(
                f"http://127.0.0.1:{server.server_port}/mcp",
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                token=api_key.plaintext,
                origin="http://evil.example",
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    conn = db.connect(database_path)
    try:
        last_used_at = conn.execute(
            "select last_used_at from api_keys where id = ?",
            (api_key.api_key_id,),
        ).fetchone()["last_used_at"]
    finally:
        conn.close()

    assert exc.value.code == 403
    assert last_used_at is None


def test_http_mcp_returns_auth_unavailable_when_named_key_auth_db_fails(
    http_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, base_url = http_service

    def fail_connect(database_path: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(http_server_module.db, "connect", fail_connect)

    with pytest.raises(urllib.error.HTTPError) as exc:
        _post_json(
            f"{base_url}/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            token="lmcp_named-token",
            origin="http://legal.internal",
        )

    assert exc.value.code == 503
    assert _http_error_payload(exc.value) == {"error": "auth_unavailable"}


def test_http_mcp_rejects_revoked_named_user_api_key(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    _database_with_project(database_path)
    conn = db.connect(database_path)
    try:
        user = create_user(
            conn,
            email="revoked-http@example.com",
            display_name="Revoked HTTP",
            role=ROLE_BUSINESS,
        )
        api_key = create_api_key(conn, user_id=user["id"], label="revoked")
        conn.execute(
            "update api_keys set status = 'revoked' where id = ?",
            (api_key.api_key_id,),
        )
        conn.commit()
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post_json(
                f"http://127.0.0.1:{server.server_port}/mcp",
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                token=api_key.plaintext,
                origin="http://legal.internal",
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert exc.value.code == 401


def test_http_mcp_rejects_disabled_named_user_api_key(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    audit_path = tmp_path / "audit.jsonl"
    _database_with_project(database_path)
    conn = db.connect(database_path)
    try:
        user = create_user(
            conn,
            email="disabled-http@example.com",
            display_name="Disabled HTTP",
            role=ROLE_BUSINESS,
        )
        api_key = create_api_key(conn, user_id=user["id"], label="disabled")
        conn.execute(
            "update users set status = 'disabled' where id = ?",
            (user["id"],),
        )
        conn.commit()
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post_json(
                f"http://127.0.0.1:{server.server_port}/mcp",
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                token=api_key.plaintext,
                origin="http://legal.internal",
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert exc.value.code == 401


def test_http_mcp_allows_absent_origin_for_non_browser_clients(http_service) -> None:
    _, base_url = http_service

    status, payload = _post_json(
        f"{base_url}/mcp",
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )

    assert status == 200
    tool_names = {tool["name"] for tool in payload["result"]["tools"]}
    assert "resolve_project" in tool_names
    assert "get_project_fields" in tool_names
    assert "get_project_context" not in tool_names
