# Team Deployment

Legal-MCP team deployment lets one operator maintain the canonical legal database while team members query the same shared context from Codex, Cursor, Claude Desktop, or another MCP client.

## Architecture

```text
Maintainer import
      |
      v
/data/legal.db
      |
      v
legal-mcp serve-http
      |
      v
legal-mcp proxy on each desktop
      |
      v
AI desktop client
```

## Operator setup

1. Choose an intranet host reachable by team members.

2. Create a long random token:

```sh
export LEGAL_MCP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

3. Import the current legal project ledger:

```sh
legal-mcp import project-ledger.xlsx --db /data/legal.db
```

4. Start the HTTP MCP server:

```sh
legal-mcp serve-http \
  --host 0.0.0.0 \
  --port 8765 \
  --db /data/legal.db \
  --audit-log /data/audit.jsonl \
  --token "$LEGAL_MCP_TOKEN"
```

5. Check health:

```sh
legal-mcp doctor --remote-url http://legal-mcp.internal:8765/mcp
```

Expected output includes:

```text
Legal-MCP doctor: healthy
ok: remote HTTP server is healthy: http://legal-mcp.internal:8765/mcp
```

## Docker Compose

```sh
export LEGAL_MCP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
mkdir -p data
legal-mcp import project-ledger.xlsx --db data/legal.db
docker compose up --build
```

The server listens on:

```text
http://localhost:8765/mcp
```

## v1.2 Enterprise Permissions

The v1.1 shared-token deployment remains available for small trusted pilots.
For v1.2 enterprise permissions, create named local users with roles:
`admin`, `legal`, `business`, and `auditor`.

Bootstrap the first admin:

```sh
legal-mcp admin create-user \
  --email admin@example.com \
  --display-name "Admin User" \
  --role admin \
  --password "replace-with-a-long-random-password" \
  --db /data/legal.db
```

Run the lightweight Admin Web UI:

```sh
legal-mcp serve-admin \
  --host 127.0.0.1 \
  --port 8766 \
  --db /data/legal.db
```

Keep Admin Web bound to `127.0.0.1` and reach it through an SSH tunnel, or put
it behind a TLS reverse proxy before binding it to a network interface. Admin
Web handles passwords, session cookies, and one-time API key display, so do not
serve it as plain HTTP on an intranet.

Use the Admin Web UI to create legal, business, and auditor users, issue
per-user API keys, and grant project access. Legal and admin users can see all
projects. Business users start with no project visibility and need project
access grants before their API keys can query project data. Auditor users are
for audit review and cannot query project content.

## Team member setup

Each team member installs Legal-MCP locally and configures their AI client to run a local proxy.

Codex:

```sh
export LEGAL_MCP_API_KEY="lmcp_replace_with_the_user_api_key"

legal-mcp setup \
  --client codex \
  --remote-url http://legal-mcp.internal:8765/mcp \
  --token "$LEGAL_MCP_API_KEY"
```

Equivalent one-line form:

```sh
legal-mcp setup --client codex --remote-url http://legal-mcp.internal:8765/mcp --token "$LEGAL_MCP_API_KEY"
```

Cursor:

```sh
legal-mcp setup \
  --client cursor \
  --remote-url http://legal-mcp.internal:8765/mcp \
  --token "$LEGAL_MCP_API_KEY"
```

Generic stdio config:

```sh
legal-mcp setup \
  --client generic \
  --remote-url http://legal-mcp.internal:8765/mcp \
  --token "$LEGAL_MCP_API_KEY"
```

The generated stdio entry runs:

```sh
legal-mcp proxy --url http://legal-mcp.internal:8765/mcp --token "$LEGAL_MCP_API_KEY"
```

For v1.1 shared-token pilots only, use `LEGAL_MCP_TOKEN` instead. In v1.2,
using the shared token bypasses named-user attribution and project grants.

## Smoke test

Ask the AI client:

```text
查询 Mgame 项目的发行对接人，用于合同沟通。
```

Expected answer:

```text
发行对接人是沪小胖。
```

## Audit log

Every MCP tool call writes to:

```text
/data/audit.jsonl
```

Each record includes timestamp, tool name, argument summary, rationale, source client, result status, and error code when applicable.

v1.2 also records DB-backed disclosure audit events for named-user access,
including the user, role, project, tool name, argument summary, rationale,
result status, and disclosure decision.

## Operational rules

- Rotate `LEGAL_MCP_TOKEN` if a team member leaves a v1.1 pilot. For v1.2,
  revoke that user's API key and remove project grants.
- Keep `/data/legal.db` and `/data/audit.jsonl` on an encrypted disk or protected intranet server.
- The v1.1 HTTP server is intended for trusted intranet use.
- Use a reverse proxy with TLS before exposing the service beyond a trusted internal network.
