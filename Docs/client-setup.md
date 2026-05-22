# MCP Client Setup

Run `legal-mcp setup` for guided configuration, or pass a client explicitly:

```sh
legal-mcp setup --client cursor
```

Legal-MCP writes a stdio server entry that runs:

```sh
legal-mcp serve --db ~/.legal-mcp/legal.db --audit-log ~/.legal-mcp/audit.jsonl
```

## Supported Clients

| Client | Command | Default config path |
| --- | --- | --- |
| Claude Desktop | `legal-mcp setup --client claude` | `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS |
| Cursor | `legal-mcp setup --client cursor` | `~/.cursor/mcp.json` |
| Windsurf | `legal-mcp setup --client windsurf` | `~/.codeium/windsurf/mcp_config.json` |
| VS Code / GitHub Copilot | `legal-mcp setup --client vscode` | `~/Library/Application Support/Code/User/mcp.json` on macOS |
| Codex | `legal-mcp setup --client codex` | `~/.codex/config.toml` |
| Generic stdio JSON | `legal-mcp setup --client generic` | `~/.legal-mcp/legal-mcp-stdio.json` |

Use `--config PATH` to write somewhere else, `--db PATH` to choose a database,
and `--audit-log PATH` to choose the audit log file.

After setup, run:

```sh
legal-mcp doctor
```

If the client supports manually adding MCP servers, use the generic stdio config
or point it at `legal-mcp serve`.

## Remote proxy mode

For team deployments, each desktop client can keep using a local stdio MCP entry while forwarding requests to the shared intranet Legal-MCP server.

```sh
legal-mcp setup \
  --client codex \
  --remote-url http://legal-mcp.internal:8765/mcp \
  --token "$LEGAL_MCP_TOKEN"
```

The generated server command is:

```sh
legal-mcp proxy --url http://legal-mcp.internal:8765/mcp --token "$LEGAL_MCP_TOKEN"
```

Run a remote health check:

```sh
legal-mcp doctor --remote-url http://legal-mcp.internal:8765/mcp
```
