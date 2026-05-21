# Real Data Trial

Use this checklist for Phase 7: validate Legal-MCP with three to five real legal projects before adding any new product surface.

## 1. Prepare a Ledger

Start from `data/import_templates/project_ledger.csv`.

Replace the example row with real project rows. Keep `项目代号`, `游戏名称`, and `上线状态`; they are required. Leave unknown or sensitive columns out unless you want Legal-MCP to report them as import warnings.

## 2. Import Into a Trial Database

```sh
legal-mcp import path/to/real-project-ledger.csv --db ./trial-legal.db
```

Read the import report:

- `projects` should match the number of source projects.
- `licenses` and `risks` may be higher because ledger rows fan out into child records.
- `Warnings` identify non-empty ledger columns that were not imported.
- `Errors` must be fixed before using the trial database.

## 3. Configure One Client

```sh
legal-mcp setup --client cursor --db ./trial-legal.db
legal-mcp doctor --db ./trial-legal.db
```

Use any supported client: `claude`, `cursor`, `windsurf`, `vscode`, `codex`, or `generic`.

## 4. Ask Trial Questions

Ask the connected AI client:

- What is the legal status of PROJECT_CODE?
- What licenses and authorizations does PROJECT_CODE have?
- Which projects have open legal risks?
- Which licenses expire soon?

Record any missing fields, ambiguous project names, confusing import warnings, or answers that are not useful to a legal user.

## 5. Done Criteria

Phase 7 is done when at least one real project query is useful, ambiguous names do not return wrong context, and the import report is understandable to a legal user.
