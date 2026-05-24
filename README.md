# Legal-MCP

Local SQLite-backed MCP server for legal project context.

## Install

Install with `uv` and start the guided setup:

```sh
uv tool install --upgrade legal-mcp && legal-mcp setup
```

The included installer script does the same thing: it runs
`uv tool install --upgrade legal-mcp`, then immediately launches
`legal-mcp setup`. If you already know the client you want to configure, pass
setup arguments through the installer:

```sh
./install.sh --client cursor
```

For local development from this checkout:

```sh
LEGAL_MCP_PACKAGE=. ./install.sh --client cursor
```

## Common Commands

Run `legal-mcp setup --client CLIENT` to write a local stdio MCP server config.
Supported clients are `claude`, `claude-code`, `cursor`, `windsurf`, `vscode`,
`codex`, and `generic`. Use `claude` for Claude Desktop and `claude-code` for
Claude Code. You can re-run setup later to repair or update the config.

Import legal project data from CSV or XLSX:

```sh
legal-mcp import path/to/projects.csv
legal-mcp import path/to/project-ledger.xlsx
```

Keep real client data, local trial databases, CSV exports, XLSX ledgers, and
other working files outside Git. The repository intentionally ships with empty data directories only.

Check install health, including database schema and an optional client config:

```sh
legal-mcp doctor
legal-mcp doctor --config ~/.cursor/mcp.json
```

Run the stdio MCP server directly:

```sh
legal-mcp serve
```

### v1.3 Minimum Disclosure

Legal-MCP v1.3 is a breaking security upgrade. Full project-context queries are
not allowed by default. Clients must use fine-grained tools, request explicit
fields, or call the planner entry point so Legal-MCP can choose the minimum
necessary fields.

`get_project_context` is deprecated and no longer returns complete project,
license, contract, and risk context. Use `tools/list` to inspect the tool
catalog and select a fine-grained tool.

The v1.3 query tools include:

- `describe_my_access` for the current user's visible projects and readable
  fields. This is the right tool for questions like "我能访问哪些项目？" or
  "查询用户权限".
- `get_project_fields` for one or more explicit project fields. Responses only
  include requested fields and do not automatically include project identity
  fields.
- `list_project_contracts` and `list_project_licenses` for scoped project
  contract and license fields.

Project lookup accepts project codes, project names, aliases, and user questions
that contain a single project identifier. When a project is not found, project
queries include the current user's visible project and field summary under
`error.details.access` so users can distinguish missing data from missing access.
If an MCP client mistakenly sends a user-permission question to `resolve_project`,
Legal-MCP returns the access summary instead of treating the question as a
project name.

Both stdio and HTTP transports run startup checks for schema compatibility.
Remote update checks are optional and never block startup.

## MCP Client Configuration

Run `legal-mcp setup --client CLIENT` to write a local stdio MCP server config.
You can re-run setup later to repair or update the config.

Common client conventions:

| Client | Default config path | Server map key |
| --- | --- | --- |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS | `mcpServers` |
| Claude Code | `~/.claude.json` via `claude mcp add --scope user` | `mcpServers` |
| Cursor | `~/.cursor/mcp.json` | `mcpServers` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` |
| VS Code / GitHub Copilot | `~/Library/Application Support/Code/User/mcp.json` on macOS | `servers` |
| Codex | `~/.codex/config.toml` | `mcp_servers` |

Supported setup clients are `claude`, `claude-code`, `cursor`, `windsurf`,
`vscode`, `codex`, and `generic`.

For local development, point client config at the checkout instead of a globally
installed `legal-mcp` binary so newly added tools are visible immediately after
restarting the MCP client. For Codex, `~/.codex/config.toml` can use:

```toml
[mcp_servers."legal-mcp"]
command = "uv"
args = [
  "--directory",
  "/Users/haoran/workspace/Legal-MCP",
  "run",
  "legal-mcp",
  "serve",
  "--db",
  "/Users/haoran/.legal-mcp/legal.db",
  "--audit-log",
  "/Users/haoran/.legal-mcp/audit.jsonl",
]
```

## Team Deployment

For a small team pilot, run one shared Legal-MCP HTTP server on an intranet host and let each team member connect through a local stdio proxy.

Operator:

```sh
export LEGAL_MCP_TOKEN="replace-with-a-long-random-token"
legal-mcp import project-ledger.xlsx --db /data/legal.db
legal-mcp serve-http \
  --host 0.0.0.0 \
  --port 8765 \
  --db /data/legal.db \
  --audit-log /data/audit.jsonl \
  --token "$LEGAL_MCP_TOKEN"
```

Team member:

```sh
legal-mcp setup \
  --client codex \
  --remote-url http://legal-mcp.internal:8765/mcp \
  --token "$LEGAL_MCP_TOKEN"
```

Clients that use the generated stdio config will run:

```sh
legal-mcp proxy --url http://legal-mcp.internal:8765/mcp --token "$LEGAL_MCP_TOKEN"
```

Claude Code users should choose `claude-code` instead of `claude`:

```sh
legal-mcp setup \
  --client claude-code \
  --remote-url http://legal-mcp.internal:8765/mcp \
  --token "$LEGAL_MCP_TOKEN"

claude mcp list
```

### v1.2 Named User Tokens

The v1.1 shared-token HTTP setup remains available for small trusted pilots. For
v1.2 enterprise permissions, bootstrap an admin user and run the Admin Web UI:

```sh
legal-mcp admin create-user \
  --email admin@example.com \
  --display-name "Admin User" \
  --role admin \
  --password "replace-with-a-long-random-password" \
  --db /data/legal.db

legal-mcp serve-admin \
  --host 127.0.0.1 \
  --port 8766 \
  --db /data/legal.db
```

The Admin Web UI creates `legal`, `business`, and `auditor` users, issues
per-user API keys, and grants project access for users who need scoped project
visibility.

For v1.2 clients, use each user's Admin-generated API key as the MCP proxy
token:

```sh
export LEGAL_MCP_API_KEY="lmcp_replace_with_the_user_api_key"

legal-mcp setup \
  --client codex \
  --remote-url http://legal-mcp.internal:8765/mcp \
  --token "$LEGAL_MCP_API_KEY"
```

Keep the Admin Web UI on `127.0.0.1` and manage it through an SSH tunnel, or
put it behind a TLS reverse proxy before binding it to a network interface. The
Admin UI handles passwords, session cookies, and one-time API key display.

Keep deployment notes that contain hostnames, client paths, tokens, or real data
in local documents outside Git.
