"""HTTP transport for shared Legal-MCP team deployments."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from legal_mcp import db
from legal_mcp.identity import verify_api_key
from legal_mcp.mcp_protocol import handle_message
from legal_mcp.policy import AccessContext


class LegalMCPHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        database_path: str | Path,
        audit_path: str | Path,
        bearer_token: str,
        allowed_origins: tuple[str, ...],
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.database_path = Path(database_path)
        self.audit_path = Path(audit_path)
        self.bearer_token = bearer_token
        self.allowed_origins = allowed_origins


class LegalMCPHTTPRequestHandler(BaseHTTPRequestHandler):
    server: LegalMCPHTTPServer

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._handle_healthz()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        access_context = self._resolve_access_context()
        if access_context is None:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if not self._origin_allowed():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            message = json.loads(body.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return

        response = handle_message(
            message,
            database_path=self.server.database_path,
            audit_path=self.server.audit_path,
            access_context=access_context,
        )
        if response is None:
            self._send_json(HTTPStatus.ACCEPTED, {})
            return
        self._send_json(HTTPStatus.OK, response)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle_healthz(self) -> None:
        try:
            db.initialize_database(self.server.database_path)
            self._send_json(HTTPStatus.OK, {"service": "legal-mcp", "database": "ready"})
        except Exception:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"service": "legal-mcp", "database": "unavailable"},
            )

    def _resolve_access_context(self) -> AccessContext | None:
        authorization = self.headers.get("Authorization")
        if authorization is None:
            return None

        scheme, _, token = authorization.partition(" ")
        if scheme != "Bearer" or not token:
            return None
        if token == self.server.bearer_token:
            return AccessContext.legacy()

        conn = db.connect(self.server.database_path)
        try:
            verified = verify_api_key(conn, token)
        finally:
            conn.close()
        if verified is None:
            return None
        return AccessContext.from_user(
            verified.user,
            api_key_id=verified.api_key["id"],
        )

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin in self.server.allowed_origins

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_http_server(
    *,
    host: str,
    port: int,
    database_path: str | Path,
    audit_path: str | Path,
    bearer_token: str,
    allowed_origins: tuple[str, ...],
) -> LegalMCPHTTPServer:
    if not bearer_token:
        raise ValueError("bearer token is required")
    return LegalMCPHTTPServer(
        (host, port),
        LegalMCPHTTPRequestHandler,
        database_path=database_path,
        audit_path=audit_path,
        bearer_token=bearer_token,
        allowed_origins=allowed_origins,
    )


def serve_http(
    *,
    host: str,
    port: int,
    database_path: str | Path,
    audit_path: str | Path,
    bearer_token: str,
    allowed_origins: tuple[str, ...],
) -> None:
    db.initialize_database(database_path)
    server = build_http_server(
        host=host,
        port=port,
        database_path=database_path,
        audit_path=audit_path,
        bearer_token=bearer_token,
        allowed_origins=allowed_origins,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
