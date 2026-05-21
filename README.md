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
Supported clients are `claude`, `cursor`, `windsurf`, `vscode`, `codex`, and
`generic`. You can re-run setup later to repair or update the config. See
[Docs/client-setup.md](Docs/client-setup.md) for client-specific paths and
options.

Import legal project data from CSV or XLSX:

```sh
legal-mcp import path/to/projects.csv
legal-mcp import path/to/project-ledger.xlsx
```

For a real data trial, start from `data/import_templates/project_ledger.csv`,
replace the example row with three to five real projects, then follow
[Docs/real-data-trial.md](Docs/real-data-trial.md).

Check install health, including database schema and an optional client config:

```sh
legal-mcp doctor
legal-mcp doctor --config ~/.cursor/mcp.json
```

Run the stdio MCP server directly:

```sh
legal-mcp serve
```

## MCP Client Configuration

Run `legal-mcp setup --client CLIENT` to write a local stdio MCP server config.
You can re-run setup later to repair or update the config.

Common client conventions:

| Client | Default config path | Server map key |
| --- | --- | --- |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS | `mcpServers` |
| Cursor | `~/.cursor/mcp.json` | `mcpServers` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` |
| VS Code / GitHub Copilot | `~/Library/Application Support/Code/User/mcp.json` on macOS | `servers` |
| Codex | `~/.codex/config.toml` | `mcp_servers` |

Supported setup clients are `claude`, `cursor`, `windsurf`, `vscode`, `codex`,
and `generic`.
