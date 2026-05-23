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
from legal_mcp.disclosure_audit import list_audit_events
from legal_mcp.identity import (
    ACTIVE,
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_BUSINESS,
    ROLE_LEGAL,
    create_api_key,
    create_user,
    hash_token,
    verify_password,
)

_SESSION_COOKIE = "lmcp_admin"
_SESSION_HOURS = 8
_AUDIT_EVENT_LIMIT = 100
_ALLOWED_ROLES = {ROLE_ADMIN, ROLE_AUDITOR, ROLE_BUSINESS, ROLE_LEGAL}


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
        if path == "/login":
            self._handle_login()
            return

        if not path.startswith("/admin/"):
            self._send_html(
                HTTPStatus.NOT_FOUND,
                self._page("Not Found", "<p>Not found</p>"),
            )
            return

        admin = self._current_admin()
        if admin is None:
            self._redirect("/login")
            return

        if path == "/admin/users/create":
            self._handle_create_user()
            return
        if path == "/admin/grants/create":
            self._handle_create_grant(admin)
            return
        if path == "/admin/keys/create":
            self._handle_create_key()
            return

        self._send_html(
            HTTPStatus.NOT_FOUND,
            self._page("Not Found", "<p>Not found</p>"),
        )

    def _handle_login(self) -> None:
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

    def _handle_create_user(self) -> None:
        fields = self._read_form_fields()
        email = fields.get("email", "").strip()
        display_name = fields.get("display_name", "").strip()
        role = fields.get("role", "").strip()
        if not email:
            self._send_form_error(HTTPStatus.BAD_REQUEST, "Email is required.")
            return
        if not display_name:
            self._send_form_error(HTTPStatus.BAD_REQUEST, "Name is required.")
            return
        if not role:
            self._send_form_error(HTTPStatus.BAD_REQUEST, "Role is required.")
            return
        if role not in _ALLOWED_ROLES:
            self._send_form_error(HTTPStatus.BAD_REQUEST, "Invalid role.")
            return

        conn = db.connect(self.server.database_path)
        try:
            try:
                create_user(conn, email=email, display_name=display_name, role=role)
            except sqlite3.IntegrityError as exc:
                if "users.email" in str(exc):
                    self._send_form_error(
                        HTTPStatus.CONFLICT,
                        "A user with that email already exists.",
                    )
                    return
                self._send_form_error(HTTPStatus.BAD_REQUEST, "Could not create user.")
                return
        finally:
            conn.close()
        self._redirect("/admin/users")

    def _handle_create_grant(self, admin: sqlite3.Row) -> None:
        fields = self._read_form_fields()
        try:
            user_id = self._parse_required_int(fields, "user_id", "User")
            project_id = self._parse_required_int(fields, "project_id", "Project")
        except ValueError as exc:
            self._send_form_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        conn = db.connect(self.server.database_path)
        try:
            try:
                conn.execute(
                    """
                    insert or ignore into project_access
                      (user_id, project_id, granted_by_user_id)
                    values (?, ?, ?)
                    """,
                    (user_id, project_id, admin["id"]),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                self._send_form_error(
                    HTTPStatus.BAD_REQUEST,
                    "User or project does not exist.",
                )
                return
        finally:
            conn.close()
        self._redirect("/admin/users")

    def _handle_create_key(self) -> None:
        fields = self._read_form_fields()
        try:
            user_id = self._parse_required_int(fields, "user_id", "User")
        except ValueError as exc:
            self._send_form_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        label = fields.get("label", "").strip()
        if not label:
            self._send_form_error(HTTPStatus.BAD_REQUEST, "Label is required.")
            return

        conn = db.connect(self.server.database_path)
        try:
            try:
                created_key = create_api_key(conn, user_id=user_id, label=label)
            except sqlite3.IntegrityError:
                self._send_form_error(HTTPStatus.BAD_REQUEST, "User does not exist.")
                return
        finally:
            conn.close()
        message = (
            "Created API key "
            f"{created_key.prefix}: {created_key.plaintext}"
        )
        self._send_users_page(message=message)

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
        expires_at = _parse_session_expires_at(row["expires_at"])
        if expires_at is None:
            return None
        if expires_at <= datetime.now(timezone.utc):
            return None
        return row

    def _send_users_page(self, message: str | None = None) -> None:
        conn = db.connect(self.server.database_path)
        try:
            user_rows = conn.execute(
                """
                select id, email, display_name, role, status, created_at
                from users
                order by id
                """
            ).fetchall()
            project_rows = conn.execute(
                """
                select id, project_code, name
                from projects
                order by id
                """
            ).fetchall()
            grant_rows = conn.execute(
                """
                select
                  project_access.id,
                  users.email,
                  projects.project_code,
                  projects.name,
                  project_access.created_at
                from project_access
                join users on users.id = project_access.user_id
                join projects on projects.id = project_access.project_id
                order by project_access.id
                """
            ).fetchall()
            key_rows = conn.execute(
                """
                select
                  api_keys.id,
                  users.email,
                  api_keys.key_prefix,
                  api_keys.label,
                  api_keys.status,
                  api_keys.created_at
                from api_keys
                join users on users.id = api_keys.user_id
                order by api_keys.id
                """
            ).fetchall()
        finally:
            conn.close()

        user_options = "\n".join(
            f"<option value=\"{html.escape(str(row['id']))}\">"
            f"{html.escape(str(row['id']))} - {html.escape(row['email'])}"
            "</option>"
            for row in user_rows
        )
        project_options = "\n".join(
            f"<option value=\"{html.escape(str(row['id']))}\">"
            f"{html.escape(str(row['id']))} - {html.escape(row['project_code'])}: {html.escape(row['name'])}"
            "</option>"
            for row in project_rows
        )
        role_options = "\n".join(
            f"<option value=\"{html.escape(role)}\">{html.escape(role)}</option>"
            for role in (ROLE_BUSINESS, ROLE_LEGAL, ROLE_AUDITOR, ROLE_ADMIN)
        )
        message_html = ""
        if message is not None:
            message_html = f"<p>{html.escape(message)}</p>"

        user_body_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(str(row['id']))}</td>"
            f"<td>{html.escape(row['email'])}</td>"
            f"<td>{html.escape(row['display_name'])}</td>"
            f"<td>{html.escape(row['role'])}</td>"
            f"<td>{html.escape(row['status'])}</td>"
            f"<td>{html.escape(row['created_at'])}</td>"
            "</tr>"
            for row in user_rows
        )
        grant_body_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(str(row['id']))}</td>"
            f"<td>{html.escape(row['email'])}</td>"
            f"<td>{html.escape(row['project_code'])}</td>"
            f"<td>{html.escape(row['name'])}</td>"
            f"<td>{html.escape(row['created_at'])}</td>"
            "</tr>"
            for row in grant_rows
        )
        key_body_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(str(row['id']))}</td>"
            f"<td>{html.escape(row['email'])}</td>"
            f"<td>{html.escape(row['key_prefix'])}</td>"
            f"<td>{html.escape(row['label'])}</td>"
            f"<td>{html.escape(row['status'])}</td>"
            f"<td>{html.escape(row['created_at'])}</td>"
            "</tr>"
            for row in key_rows
        )
        body = f"""
        <nav><a href="/admin/users">Users</a> <a href="/admin/audit">Audit</a></nav>
        <h1>Users</h1>
        {message_html}
        <h2>Create User</h2>
        <form method="post" action="/admin/users/create">
          <label>Email <input type="email" name="email" required></label>
          <label>Name <input type="text" name="display_name" required></label>
          <label>Role <select name="role" required>{role_options}</select></label>
          <button type="submit">Create User</button>
        </form>
        <table>
          <thead><tr><th>ID</th><th>Email</th><th>Name</th><th>Role</th><th>Status</th><th>Created</th></tr></thead>
          <tbody>{user_body_rows}</tbody>
        </table>
        <h2>Grant Project Access</h2>
        <form method="post" action="/admin/grants/create">
          <label>User <select name="user_id" required>{user_options}</select></label>
          <label>Project <select name="project_id" required>{project_options}</select></label>
          <button type="submit">Grant Access</button>
        </form>
        <table>
          <thead><tr><th>ID</th><th>User</th><th>Project Code</th><th>Project</th><th>Created</th></tr></thead>
          <tbody>{grant_body_rows}</tbody>
        </table>
        <h2>Create API Key</h2>
        <form method="post" action="/admin/keys/create">
          <label>User <select name="user_id" required>{user_options}</select></label>
          <label>Label <input type="text" name="label" required></label>
          <button type="submit">Create Key</button>
        </form>
        <table>
          <thead><tr><th>ID</th><th>User</th><th>Prefix</th><th>Label</th><th>Status</th><th>Created</th></tr></thead>
          <tbody>{key_body_rows}</tbody>
        </table>
        """
        self._send_html(HTTPStatus.OK, self._page("Admin Users", body))

    def _send_audit_page(self) -> None:
        conn = db.connect(self.server.database_path)
        try:
            rows = list_audit_events(conn, limit=_AUDIT_EVENT_LIMIT)
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

    def _parse_required_int(
        self,
        fields: dict[str, str],
        name: str,
        label: str,
    ) -> int:
        value = fields.get(name, "").strip()
        if not value:
            raise ValueError(f"{label} is required.")
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"{label} must be a valid ID.") from None

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

    def _send_form_error(self, status: HTTPStatus, message: str) -> None:
        body = f"""
        <nav><a href="/admin/users">Users</a></nav>
        <h1>Form Error</h1>
        <p>{html.escape(message)}</p>
        """
        self._send_html(status, self._page("Form Error", body))

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


def _parse_session_expires_at(value: str) -> datetime | None:
    try:
        expires_at = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if expires_at.tzinfo is None:
        return expires_at.replace(tzinfo=timezone.utc)
    return expires_at.astimezone(timezone.utc)
