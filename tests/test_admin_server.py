from __future__ import annotations

import http.cookiejar
import threading
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.client import HTTPResponse
from urllib.error import HTTPError
from pathlib import Path
from typing import Iterator

from legal_mcp import db
from legal_mcp.admin_server import build_admin_server
from legal_mcp.identity import (
    ROLE_ADMIN,
    ROLE_BUSINESS,
    create_user,
    hash_password,
    hash_token,
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: HTTPResponse,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


@contextmanager
def _running_admin_server(database_path: Path) -> Iterator[str]:
    server = build_admin_server(
        host="127.0.0.1",
        port=0,
        database_path=database_path,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


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


def _insert_admin_session(
    database_path: Path,
    *,
    token: str = "admin-session-token",
    expires_at: str = "2099-01-01 00:00:00",
) -> str:
    conn = db.connect(database_path)
    try:
        user = conn.execute(
            "select id from users where email = ?",
            ("admin@example.com",),
        ).fetchone()
        assert user is not None
        conn.execute(
            """
            insert into admin_sessions (user_id, session_hash, expires_at)
            values (?, ?, ?)
            """,
            (user["id"], hash_token(token), expires_at),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def _logged_in_opener(base_url: str) -> urllib.request.OpenerDirector:
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
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
    return opener


def test_admin_server_login_and_users_page_lists_admin(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    with _running_admin_server(database_path) as base_url:
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(cookie_jar),
        )
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


def test_login_sets_admin_cookie_and_redirects_to_users(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    with _running_admin_server(database_path) as base_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )
        login_body = urllib.parse.urlencode(
            {"email": "admin@example.com", "password": "secret"}
        ).encode("utf-8")
        login_request = urllib.request.Request(
            f"{base_url}/login",
            data=login_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            opener.open(login_request, timeout=5)
        except HTTPError as response:
            assert response.code == 303
            assert response.headers["Location"] == "/admin/users"
            set_cookie = response.headers["Set-Cookie"]
        else:
            raise AssertionError("login did not redirect")

        assert "lmcp_admin=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=Lax" in set_cookie


def test_unauthenticated_users_page_redirects_to_login(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    with _running_admin_server(database_path) as base_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

        try:
            opener.open(f"{base_url}/admin/users", timeout=5)
        except HTTPError as response:
            assert response.code == 303
            assert response.headers["Location"] == "/login"
        else:
            raise AssertionError("unauthenticated request did not redirect")


def test_users_page_accepts_naive_unexpired_session_timestamp(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    expires_at = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    token = _insert_admin_session(database_path, expires_at=expires_at)
    with _running_admin_server(database_path) as base_url:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(
            f"{base_url}/admin/users",
            headers={"Cookie": f"lmcp_admin={token}"},
        )

        with opener.open(request, timeout=5) as response:
            body = response.read().decode("utf-8")

        assert response.status == 200
        assert "admin@example.com" in body


def test_bad_or_expired_session_redirects_to_login(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    token = _insert_admin_session(
        database_path,
        token="expired-session-token",
        expires_at="2000-01-01 00:00:00",
    )
    with _running_admin_server(database_path) as base_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )
        for cookie_token in (token, "bad-session-token"):
            request = urllib.request.Request(
                f"{base_url}/admin/users",
                headers={"Cookie": f"lmcp_admin={cookie_token}"},
            )

            try:
                opener.open(request, timeout=5)
            except HTTPError as response:
                assert response.code == 303
                assert response.headers["Location"] == "/login"
            else:
                raise AssertionError("bad or expired session did not redirect")


def test_unauthenticated_admin_post_redirects_to_login(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    with _running_admin_server(database_path) as base_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )
        request = urllib.request.Request(
            f"{base_url}/admin/users/create",
            data=b"",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            opener.open(request, timeout=5)
        except HTTPError as response:
            assert response.code == 303
            assert response.headers["Location"] == "/login"
        else:
            raise AssertionError("unauthenticated admin POST did not redirect")


def test_admin_can_create_business_user_and_grant_project(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    with _running_admin_server(database_path) as base_url:
        opener = _logged_in_opener(base_url)
        create_user_body = urllib.parse.urlencode(
            {
                "email": "business@example.com",
                "display_name": "Business User",
                "role": ROLE_BUSINESS,
            }
        ).encode("utf-8")
        create_user_request = urllib.request.Request(
            f"{base_url}/admin/users/create",
            data=create_user_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with opener.open(create_user_request, timeout=5) as response:
            assert response.status == 200

        with opener.open(f"{base_url}/admin/users", timeout=5) as response:
            body = response.read().decode("utf-8")

        assert "business@example.com" in body

        conn = db.connect(database_path)
        try:
            user = conn.execute(
                "select id from users where email = ?",
                ("business@example.com",),
            ).fetchone()
            project = conn.execute(
                "select id from projects where project_code = ?",
                ("ADMIN",),
            ).fetchone()
            assert user is not None
            assert project is not None
            user_id = user["id"]
            project_id = project["id"]
        finally:
            conn.close()

        create_grant_body = urllib.parse.urlencode(
            {"user_id": str(user_id), "project_id": str(project_id)}
        ).encode("utf-8")
        create_grant_request = urllib.request.Request(
            f"{base_url}/admin/grants/create",
            data=create_grant_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with opener.open(create_grant_request, timeout=5) as response:
            assert response.status == 200

        conn = db.connect(database_path)
        try:
            grant = conn.execute(
                """
                select * from project_access
                where user_id = ? and project_id = ?
                """,
                (user_id, project_id),
            ).fetchone()
        finally:
            conn.close()

        assert grant is not None


def test_admin_can_create_api_key_and_see_plaintext_once(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    with _running_admin_server(database_path) as base_url:
        opener = _logged_in_opener(base_url)
        conn = db.connect(database_path)
        try:
            user = conn.execute(
                "select id from users where email = ?",
                ("admin@example.com",),
            ).fetchone()
            assert user is not None
            user_id = user["id"]
        finally:
            conn.close()

        create_key_body = urllib.parse.urlencode(
            {"user_id": str(user_id), "label": "pytest"}
        ).encode("utf-8")
        create_key_request = urllib.request.Request(
            f"{base_url}/admin/keys/create",
            data=create_key_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with opener.open(create_key_request, timeout=5) as response:
            body = response.read().decode("utf-8")

        assert response.status == 200
        assert "lmcp_" in body

        conn = db.connect(database_path)
        try:
            key = conn.execute(
                "select key_prefix, key_hash, label from api_keys where user_id = ?",
                (user_id,),
            ).fetchone()
        finally:
            conn.close()

        assert key is not None
        assert key["label"] == "pytest"
        assert key["key_prefix"] in body
        assert key["key_hash"] not in body


def test_audit_page_shows_only_recent_events(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_admin_and_project(database_path)
    token = _insert_admin_session(database_path)
    conn = db.connect(database_path)
    try:
        conn.execute(
            """
            insert into audit_events (tool_name, arguments_summary, result_status)
            values (?, ?, ?)
            """,
            ("overflow-old", "{}", "success"),
        )
        conn.executemany(
            """
            insert into audit_events (tool_name, arguments_summary, result_status)
            values (?, ?, ?)
            """,
            [(f"recent-tool-{index}", "{}", "success") for index in range(100)],
        )
        conn.commit()
    finally:
        conn.close()

    with _running_admin_server(database_path) as base_url:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(
            f"{base_url}/admin/audit",
            headers={"Cookie": f"lmcp_admin={token}"},
        )

        with opener.open(request, timeout=5) as response:
            body = response.read().decode("utf-8")

    assert response.status == 200
    assert "recent-tool-99" in body
    assert "overflow-old" not in body
