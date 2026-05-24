# Agent Observability

Legal-MCP v1.4 routes `agent_query` through a server-side LangGraph workflow.
The graph selects approved internal read tools, executes them through
`legal_mcp.tools.call_tool`, writes Legal-MCP audit records, and stores run
metadata in SQLite.

## Optional Agent Dependencies

For local development from this checkout:

```sh
uv pip install -e ".[agent]"
```

The repository lockfile also supports:

```sh
uv sync --extra agent
```

## Model Configuration

Set an OpenAI-compatible model endpoint for the agent runtime:

```sh
export OPENAI_API_KEY="replace-with-agent-key"
export OPENAI_BASE_URL="http://localhost:4000/v1"
export LEGAL_MCP_AGENT_MODEL="gpt-4.1-mini"
```

`OPENAI_BASE_URL` is optional when using the default OpenAI API endpoint.
`LEGAL_MCP_AGENT_MODEL` defaults to `gpt-4.1-mini`.

Use `LEGAL_MCP_AGENT_PUBLIC_ONLY=true` or `--agent-public-only` on
`legal-mcp serve` / `legal-mcp serve-http` when MCP clients should list only
`agent_query`.

## Self-Hosted Langfuse

Langfuse tracing is optional and disabled unless all required environment
variables are present:

```sh
export LANGFUSE_PUBLIC_KEY="pk-lf-local"
export LANGFUSE_SECRET_KEY="sk-lf-local"
export LANGFUSE_BASE_URL=http://127.0.0.1:3000
```

When Legal-MCP and Langfuse run in one private Docker network, use the private
service name instead:

```sh
export LANGFUSE_BASE_URL=http://langfuse-web:3000
```

Langfuse Cloud is not the production default. Production observability must use
self-hosted Langfuse on localhost, a private Docker network, or an intranet
host. Do not point production `LANGFUSE_BASE_URL` at
`https://cloud.langfuse.com`.

Trace metadata is sanitized: it may include `thread_id`, selected tool name,
status, and error code, but not raw project, contract, license, or risk result
payloads.

## Checkpoints And Runs

Agent checkpoints default to a SQLite file named
`legal-mcp-agent-checkpoints.sqlite` next to the Legal-MCP database. Each
completed `agent_query` inserts a row into `agent_runs`:

```sql
select thread_id, status, selected_tool, error_code, created_at
from agent_runs
order by id desc
limit 20;
```

Use `agent_runs` and the normal Legal-MCP disclosure audit tables as the source
of truth for what the agent selected and what data was disclosed or denied.

## Langflow

Langflow is prototype-only. Use it only with development or mock data, and do
not connect it to production Legal-MCP data without network/auth isolation.
Production routing is owned by the checked-in LangGraph workflow, capability
registry, field authorization, and audit layer.
