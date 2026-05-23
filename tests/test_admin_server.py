from __future__ import annotations

import http.cookiejar
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from legal_mcp import db
from legal_mcp.admin_server import build_admin_server
from legal_mcp.identity import ROLE_ADMIN, create_user, hash_password


def _database_with_admin_and_project(path: Path) -> None:
    db.initialize_database(path)
    conn = db.connect(path)
    try:
        create_user(
            conn,
            email="admin@example.com",
            display_name="Admin User",
            role=ROLE_ADMIN,
            password_hash=hash_password("secret"),
        )
        conn.execute(
            """
            insert into projects (project_code, name, stage, release_team, contact_person)
            values (?, ?, ?, ?, ?)
            """,
            ("ADMIN", "Admin Project", "active", "Legal", "Admin User"),
        )
        conn.commit()
    finally:
        conn.close()


def test_admin_server_login_and_users_page_lists_admin(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    server = build_admin_server(
        host="127.0.0.1",
        port=0,
        database_path=database_path,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(cookie_jar),
        )
        base_url = f"http://127.0.0.1:{server.server_port}"
        login_body = urllib.parse.urlencode(
            {"email": "admin@example.com", "password": "secret"}
        ).encode("utf-8")
        login_request = urllib.request.Request(
            f"{base_url}/login",
            data=login_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with opener.open(login_request, timeout=5) as response:
            assert response.status == 200

        with opener.open(f"{base_url}/admin/users", timeout=5) as response:
            body = response.read().decode("utf-8")

        assert response.status == 200
        assert "admin@example.com" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
