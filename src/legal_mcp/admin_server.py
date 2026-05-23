"""Minimal admin web server for local Legal-MCP administration."""

from __future__ import annotations

import html
import secrets
import sqlite3
import urllib.parse
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from legal_mcp import db
from legal_mcp.identity import ACTIVE, ROLE_ADMIN, hash_token, verify_password

_SESSION_COOKIE = "lmcp_admin"
_SESSION_HOURS = 8


class LegalMCPAdminServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        database_path: str | Path,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.database_path = Path(database_path)


class LegalMCPAdminRequestHandler(BaseHTTPRequestHandler):
    server: LegalMCPAdminServer

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            self._send_login_page()
            return
        if path == "/login":
            self._send_login_page()
            return
        if path == "/admin/users":
            admin = self._current_admin()
            if admin is None:
                self._redirect("/login")
                return
            self._send_users_page()
            return
        if path == "/admin/audit":
            admin = self._current_admin()
            if admin is None:
                self._redirect("/login")
                return
            self._send_audit_page()
            return
        self._send_html(HTTPStatus.NOT_FOUND, self._page("Not Found", "<p>Not found</p>"))

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path != "/login":
            self._send_html(
                HTTPStatus.NOT_FOUND,
                self._page("Not Found", "<p>Not found</p>"),
            )
            return

        fields = self._read_form_fields()
        email = fields.get("email", "")
        password = fields.get("password", "")
        conn = db.connect(self.server.database_path)
        try:
            user = conn.execute(
                """
                select * from users
                where email = ? and role = ? and status = ?
                """,
                (email, ROLE_ADMIN, ACTIVE),
            ).fetchone()
            if user is None or not verify_password(password, user["password_hash"]):
                self._send_login_page(
                    HTTPStatus.UNAUTHORIZED,
                    "Invalid admin email or password.",
                )
                return

            token = secrets.token_urlsafe(32)
            expires_at = (
                datetime.now(timezone.utc) + timedelta(hours=_SESSION_HOURS)
            ).isoformat()
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

        self._redirect(
            "/admin/users",
            headers=[
                (
                    "Set-Cookie",
                    f"{_SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={_SESSION_HOURS * 3600}",
                )
            ],
        )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _current_admin(self) -> sqlite3.Row | None:
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get(_SESSION_COOKIE)
        if morsel is None or not morsel.value:
            return None

        session_hash = hash_token(morsel.value)
        conn = db.connect(self.server.database_path)
        try:
            row = conn.execute(
                """
                select
                  users.id,
                  users.email,
                  users.display_name,
                  users.role,
                  users.status,
                  admin_sessions.expires_at
                from admin_sessions
                join users on users.id = admin_sessions.user_id
                where admin_sessions.session_hash = ?
                """,
                (session_hash,),
            ).fetchone()
        finally:
            conn.close()
        if row is None or row["role"] != ROLE_ADMIN or row["status"] != ACTIVE:
            return None
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except (TypeError, ValueError):
            return None
        if expires_at <= datetime.now(timezone.utc):
            return None
        return row

    def _send_users_page(self) -> None:
        conn = db.connect(self.server.database_path)
        try:
            rows = conn.execute(
                """
                select id, email, display_name, role, status, created_at
                from users
                order by id
                """
            ).fetchall()
        finally:
            conn.close()

        body_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(str(row['id']))}</td>"
            f"<td>{html.escape(row['email'])}</td>"
            f"<td>{html.escape(row['display_name'])}</td>"
            f"<td>{html.escape(row['role'])}</td>"
            f"<td>{html.escape(row['status'])}</td>"
            f"<td>{html.escape(row['created_at'])}</td>"
            "</tr>"
            for row in rows
        )
        body = f"""
        <nav><a href="/admin/users">Users</a> <a href="/admin/audit">Audit</a></nav>
        <h1>Users</h1>
        <table>
          <thead><tr><th>ID</th><th>Email</th><th>Name</th><th>Role</th><th>Status</th><th>Created</th></tr></thead>
          <tbody>{body_rows}</tbody>
        </table>
        """
        self._send_html(HTTPStatus.OK, self._page("Admin Users", body))

    def _send_audit_page(self) -> None:
        conn = db.connect(self.server.database_path)
        try:
            rows = conn.execute(
                """
                select id, timestamp, user_id, source_client, tool_name,
                       rationale, result_status, error_code, response_record_count
                from audit_events
                order by id desc
                """
            ).fetchall()
        finally:
            conn.close()

        body_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(str(row['id']))}</td>"
            f"<td>{html.escape(row['timestamp'])}</td>"
            f"<td>{html.escape(str(row['user_id'] or ''))}</td>"
            f"<td>{html.escape(row['source_client'] or '')}</td>"
            f"<td>{html.escape(row['tool_name'])}</td>"
            f"<td>{html.escape(row['rationale'] or '')}</td>"
            f"<td>{html.escape(row['result_status'])}</td>"
            f"<td>{html.escape(row['error_code'] or '')}</td>"
            f"<td>{html.escape(str(row['response_record_count']))}</td>"
            "</tr>"
            for row in rows
        )
        body = f"""
        <nav><a href="/admin/users">Users</a> <a href="/admin/audit">Audit</a></nav>
        <h1>Audit Events</h1>
        <table>
          <thead><tr><th>ID</th><th>Timestamp</th><th>User</th><th>Client</th><th>Tool</th><th>Rationale</th><th>Status</th><th>Error</th><th>Records</th></tr></thead>
          <tbody>{body_rows}</tbody>
        </table>
        """
        self._send_html(HTTPStatus.OK, self._page("Admin Audit", body))

    def _send_login_page(
        self,
        status: HTTPStatus = HTTPStatus.OK,
        message: str | None = None,
    ) -> None:
        message_html = ""
        if message is not None:
            message_html = f"<p>{html.escape(message)}</p>"
        body = f"""
        <h1>Admin Login</h1>
        {message_html}
        <form method="post" action="/login">
          <label>Email <input type="email" name="email" required></label>
          <label>Password <input type="password" name="password" required></label>
          <button type="submit">Log in</button>
        </form>
        """
        self._send_html(status, self._page("Admin Login", body))

    def _read_form_fields(self) -> dict[str, str]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        body = self.rfile.read(content_length).decode("utf-8")
        parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
        return {key: values[0] for key, values in parsed.items() if values}

    def _redirect(
        self,
        location: str,
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for key, value in headers or []:
            self.send_header(key, value)
        self.end_headers()

    def _send_html(self, status: HTTPStatus, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _page(self, title: str, body: str) -> str:
        escaped_title = html.escape(title)
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escaped_title}</title>
</head>
<body>
  {body}
</body>
</html>"""


def build_admin_server(
    *,
    host: str,
    port: int,
    database_path: str | Path,
) -> LegalMCPAdminServer:
    db.initialize_database(database_path)
    return LegalMCPAdminServer(
        (host, port),
        LegalMCPAdminRequestHandler,
        database_path=database_path,
    )
