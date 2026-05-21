# Legal-MCP v1 Implementation Plan

This is the source-of-truth implementation plan for AI-assisted development.

Use this document when asking an AI coding agent to build the project step by step. The older product/design documents explain why the product exists, but this file controls what v1 must build.

## 0. Scope Guard

v1 builds only this:

```text
one-line installer
      |
      v
uv tool install legal-mcp
      |
      v
legal-mcp setup
      |
      v
CSV/XLSX import, including project ledger wide tables -> SQLite -> stdio MCP server -> desktop AI clients
```

In scope:

1. Python package named `legal-mcp`.
2. CLI command named `legal-mcp`.
3. SQLite canonical local database.
4. CSV/XLSX import pipeline for both normalized files and common project ledger wide tables.
5. stdio MCP server.
6. Client-agnostic MCP support for Claude Desktop, Cursor, Codex, and generic stdio clients.
7. Interactive `legal-mcp setup`.
8. `legal-mcp doctor`.
9. One-line install script.
10. Tests for importer, database, MCP tools, setup helpers, and stdio smoke path.

Not in v1:

1. Web GUI.
2. Docker or HTTP MCP deployment.
3. OCR/PDF extraction.
4. OA, Feishu, or CLM connectors.
5. Enterprise permissions or audit console.
6. Contract review automation.
7. Multi-tenant server.

If an implementation task tries to add anything from "Not in v1", stop and move it to `TODOS.md` instead.

## 1. Target File Layout

Create a small Python project:

```text
Legal-MCP/
  pyproject.toml
  README.md
  install.sh
  src/
    legal_mcp/
      __init__.py
      cli.py
      config.py
      db.py
      schema.sql
      import_pipeline/
        __init__.py
        csv_reader.py
        xlsx_reader.py
        ledger_adapter.py
        normalize.py
        validate.py
        upsert.py
        report.py
      mcp_server.py
      tools.py
      lookup.py
      audit.py
      setup_wizard.py
      client_configs/
        __init__.py
        claude.py
        cursor.py
        codex.py
        generic.py
      doctor.py
  data/
    import_templates/
      projects.csv
      contracts.csv
      licenses.csv
      risks.csv
      project_ledger.csv
  tests/
    test_schema.py
    test_import_pipeline.py
    test_lookup.py
    test_tools.py
    test_audit.py
    test_doctor.py
    test_stdio_smoke.py
  scripts/
    smoke_stdio_client.py
```

Keep this layout unless implementation discovers a concrete reason to change it.

## 2. Data Model Requirements

SQLite is the canonical data store.

`project_code` is the stable unique project identifier. Project names are display fields only. Project names may duplicate and may change.

Tables:

```text
projects
  id
  project_code unique not null
  name not null
  stage not null
  legal_bp
  department
  release_team
  contact_person
  website
  notes
  created_at
  updated_at

contracts
  id
  project_id not null references projects(id)
  external_key not null
  title not null
  counterparty
  signed_date
  summary
  created_at
  updated_at
  unique(project_id, external_key)

licenses
  id
  project_id not null references projects(id)
  external_key not null
  license_type not null
  identifier
  entity_name
  issuer
  approval_number
  rights_holder
  copyright_holder
  operating_entity
  actual_operator
  authorization_relation
  expiry_date
  notes
  created_at
  updated_at
  unique(project_id, external_key)

risks
  id
  project_id not null references projects(id)
  external_key not null
  description not null
  status not null
  source
  created_at
  updated_at
  unique(project_id, external_key)
```

Required indexes:

```text
projects(project_code) unique
projects(stage)
projects(name)
contracts(project_id, external_key) unique
licenses(project_id, external_key) unique
licenses(license_type)
licenses(expiry_date)
risks(project_id, external_key) unique
risks(status)
risks(project_id, status)
```

## 3. Import Pipeline

The import pipeline is shared infrastructure. CLI import and future GUI upload must use the same pipeline.

Pipeline:

```text
read CSV/XLSX
      |
      v
detect import profile
      |
      v
adapt ledger rows if needed
      |
      v
normalize rows
      |
      v
validate rows
      |
      v
upsert into SQLite
      |
      v
emit import report
```

Normalized import files:

```text
projects.csv
contracts.csv
licenses.csv
risks.csv
```

Common project ledger import files:

```text
project_ledger.csv
project_ledger.xlsx
```

The project ledger format is a first-class v1 import shape because legal users commonly maintain one wide spreadsheet where each row contains one project plus related license, credential, authorization, and risk facts. The importer must not require users to manually split this file into normalized tables before import.

Rules:

1. Users never reference SQLite internal IDs.
2. Child rows reference `project_code`.
3. Normalized project rows require `project_code`, `name`, and `stage`.
4. Normalized child rows require `project_code` and `external_key`.
5. Re-importing the same files must not duplicate rows.
6. Changed fields update existing rows.
7. The report must count created, updated, skipped, and failed rows.
8. Validation errors must include file name, row number, field name, error code, and human message.

Project ledger wide-table rules:

1. Each non-empty row represents one project and may also contain license, credential, authorization, and risk facts.
2. Required ledger columns are `项目代号`, `游戏名称`, and `上线状态`; they map to `project_code`, `name`, and `stage`.
3. Optional ledger project columns map directly when present:
   `法务BP` -> `legal_bp`,
   `部门` -> `department`,
   `发行团队` -> `release_team`,
   `对接人` -> `contact_person`,
   `官网` -> `website`,
   `备注` -> `notes`.
4. License and credential-like columns fan out into `licenses` rows. v1 must support at least:
   `版号`, `审批文号`, `ICP备案号`, `软著登记号`, `出版单位`, `商标权利人`, `软著著作权人`, `版号运营主体`, `实际运营主体`, and `内部授权关系`.
5. Ledger-derived child rows must get deterministic `external_key` values generated from `project_code` and record type, for example `publication_license`, `icp_filing`, `software_copyright`, and `rights_authorization`. This preserves idempotent re-imports even when the spreadsheet has no child IDs.
6. `风险预警` creates or updates a `risks` row when non-empty. Its `status` defaults to `open`; `source` should identify the import file; `external_key` is deterministic from `project_code` plus the normalized risk text.
7. Empty license, credential, or risk cells do not create child rows.
8. `licenses.expiry_date` is optional. `list_expiring_licenses` only considers rows where `expiry_date is not null`.
9. The import report must show both source rows and fan-out results, for example projects created/updated, licenses created/updated/skipped, and risks created/updated/skipped.
10. Unknown non-empty ledger columns must appear as import warnings with the original header name. Unknown empty columns may be ignored.

Minimum ledger fan-out mapping:

```text
project:
  项目代号 -> project_code
  游戏名称 -> name
  上线状态 -> stage
  法务BP -> legal_bp
  部门 -> department
  发行团队 -> release_team
  对接人 -> contact_person
  官网 -> website
  备注 -> notes

publication_license:
  版号 -> identifier
  审批文号 -> approval_number
  出版单位 -> issuer
  版号运营主体 -> operating_entity
  实际运营主体 -> actual_operator
  内部授权关系 -> authorization_relation

icp_filing:
  ICP备案号 -> identifier
  实际运营主体 -> actual_operator

software_copyright:
  软著登记号 -> identifier
  软著著作权人 -> copyright_holder
  实际运营主体 -> actual_operator

trademark_right:
  商标权利人 -> rights_holder

risk:
  风险预警 -> description
  default status -> open
```

## 4. MCP Tools

The server uses stdio MCP transport.

The server must be client-agnostic. Do not hard-code Claude-specific behavior into tool logic.

Tools:

```text
list_projects(stage?: string, rationale: string, source_client?: string)

get_project_context(project_id_or_name: string, rationale: string, source_client?: string)

list_expiring_licenses(days_ahead: int = 30, rationale: string, source_client?: string)

list_open_risks(project_code?: string, rationale: string, source_client?: string)
```

Every tool requires `rationale`.

`get_project_context` must include the expanded v1 project fields (`project_code`, `legal_bp`, `department`, `release_team`, `contact_person`, and `website`) and all related license records, including license records without expiry dates. `list_expiring_licenses` must filter to licenses with non-null `expiry_date` within the requested boundary.

Missing rationale returns:

```json
{
  "error": {
    "code": "missing_rationale",
    "message": "rationale is required"
  }
}
```

All tool errors use this structure:

```json
{
  "error": {
    "code": "not_found | ambiguous_project | validation_error | database_error | missing_rationale",
    "message": "human readable message",
    "candidates": [],
    "details": {}
  }
}
```

## 5. Project Lookup Rules

Lookup order for `get_project_context`:

```text
1. exact project_code match
2. exact project name match, only if one project has that name
3. fuzzy name match, only if exactly one candidate clears threshold
4. ambiguous_project error with candidates
5. not_found error
```

Never silently choose between multiple plausible projects.

## 6. Audit Logging

Every MCP tool call writes a local audit log.

Log fields:

```text
timestamp
tool_name
rationale
source_client
arguments_summary
result_status
error_code
```

Do not dump large contract summaries or excessive sensitive content into the audit log. Summarize arguments.

## 7. CLI Commands

Required commands:

```bash
legal-mcp --version
legal-mcp import PATH
legal-mcp serve
legal-mcp setup
legal-mcp doctor
```

`legal-mcp setup` must:

1. Detect or create local config directory.
2. Detect installed desktop AI clients where possible.
3. Let the user choose Claude Desktop, Cursor, Codex, and/or generic stdio.
4. Let the user choose database path.
5. Optionally run import.
6. Write client MCP config.
7. Run `legal-mcp doctor`.
8. Tell the user they can re-run `legal-mcp setup` later.

`legal-mcp doctor` must verify:

1. CLI command is available.
2. Database path exists or can be created.
3. Schema exists.
4. At least one project exists, if data has been imported.
5. MCP server can start.
6. Tools can be listed.
7. A sample tool call can run if sample data exists.

## 8. Install Experience

Primary user-facing install path:

```bash
curl -LsSf https://raw.githubusercontent.com/OWNER/REPO/main/install.sh | sh
```

`install.sh` responsibilities:

1. Check whether `uv` exists.
2. If `uv` is missing, guide or install it using the official uv install path.
3. Run `uv tool install legal-mcp`.
4. Run `legal-mcp setup`.

Do not put business logic in `install.sh`. The shell script is only a bootstrapper. Real setup logic lives in Python under `legal_mcp/setup_wizard.py`.

## 9. Test Plan

Use pytest.

The detailed test artifact is:

```text
~/.gstack/projects/Legal-MCP/haoran-unknown-eng-review-test-plan-20260521-023919.md
```

Minimum tests:

1. Schema creates all tables, constraints, and indexes.
2. Valid CSV import creates rows.
3. Valid XLSX import creates rows.
4. Missing required columns fail with row-level errors.
5. Duplicate project names are allowed when `project_code` differs.
6. Project rename updates existing `project_code`.
7. Re-import is idempotent.
8. Changed fields update rows.
9. Unknown child `project_code` fails row-level validation.
10. Duplicate child `external_key` inside one project fails or updates deterministically.
11. All MCP tools require `rationale`.
12. `get_project_context` exact `project_code` wins.
13. Ambiguous project name returns candidates.
14. Not found returns structured error.
15. Expiring license boundaries are correct.
16. Closed risks are excluded from open risk results.
17. Audit log records successful and failed calls.
18. stdio smoke test launches server, lists tools, and calls `get_project_context`.
19. Project ledger XLSX import fans one row out into project, license, and risk rows.
20. Ledger-derived child `external_key` values are deterministic and re-import is idempotent.
21. Ledger rows with blank license or risk cells do not create empty child records.
22. License rows with null `expiry_date` are retained but excluded from `list_expiring_licenses`.
23. Chinese ledger headers map to canonical fields and unknown non-empty headers are reported as warnings, not silently discarded.

No implementation step is complete until its tests pass.

## 10. Development Phases

### Phase 1: Package Skeleton

Goal: create a runnable Python package and empty CLI.

Build:

1. `pyproject.toml`
2. `src/legal_mcp/__init__.py`
3. `src/legal_mcp/cli.py`
4. pytest setup

Done when:

```bash
legal-mcp --version
pytest
```

both run successfully.

### Phase 2: SQLite Schema

Goal: create canonical DB schema.

Build:

1. `schema.sql`
2. `db.py`
3. schema initialization command/helper

Done when:

1. tests prove all tables exist.
2. tests prove constraints and indexes exist.
3. foreign keys are enabled.

### Phase 3: Import Pipeline

Goal: import CSV/XLSX into SQLite safely.

Build:

1. readers
2. ledger adapter for project wide-table imports
3. normalizer
4. validator
5. upsert layer
6. import report
7. `legal-mcp import PATH`

Done when:

1. valid sample data imports.
2. invalid rows produce row-level errors.
3. repeated import is idempotent.
4. project rename by same `project_code` updates one row.
5. project ledger XLSX imports create/update projects, licenses, and risks through one shared pipeline.
6. import reports are understandable for both normalized files and ledger wide tables.

### Phase 4: MCP Server and Tools

Goal: expose context through stdio MCP.

Build:

1. `mcp_server.py`
2. `tools.py`
3. `lookup.py`
4. `audit.py`
5. `legal-mcp serve`

Done when:

1. tools can be listed by a stdio MCP smoke client.
2. all tools require `rationale`.
3. project lookup ambiguity is handled safely.
4. audit logs are written.

### Phase 5: Setup and Doctor

Goal: make local user setup guided and recoverable.

Build:

1. `setup_wizard.py`
2. `doctor.py`
3. client config writers for Claude, Cursor, Codex, and generic stdio.

Done when:

1. `legal-mcp setup` can configure at least one client.
2. `legal-mcp doctor` can validate install health.
3. setup tells users they can re-run `legal-mcp setup`.

### Phase 6: Installer and Docs

Goal: one-line installation.

Build:

1. `install.sh`
2. README install section
3. client setup docs

Done when:

1. install script bootstraps `uv tool install legal-mcp`.
2. install script immediately launches setup.
3. README documents `legal-mcp setup`, `legal-mcp import`, `legal-mcp doctor`, and `legal-mcp serve`.

### Phase 7: Real Data Trial

Goal: validate with real legal projects.

Run:

1. Import three to five real projects, preferably from a real project ledger wide table.
2. Connect one desktop AI client.
3. Ask for project status and context.
4. Record missing fields or confusing outputs.

Done when:

1. at least one real project query is useful.
2. ambiguous names do not return wrong context.
3. import report is understandable to a legal user.

## 11. AI Coding Agent Prompt

Use this prompt to start implementation:

```text
Implement Legal-MCP v1 using Docs/v1-implementation-plan.md as the source of truth.

Do not implement Web UI, Docker/HTTP deployment, OCR/PDF extraction, external system connectors, enterprise permissions, or contract review automation.

Follow the phases in order. For each phase, write tests first or alongside implementation, run pytest, and stop with a short status report before moving to the next phase.

Use the detailed test requirements in ~/.gstack/projects/Legal-MCP/haoran-unknown-eng-review-test-plan-20260521-023919.md.
```

## 12. Stop Conditions

Stop and ask before continuing if:

1. A chosen MCP library does not support stdio cleanly.
2. Claude/Cursor/Codex config paths conflict with current official docs.
3. Real project ledger data contains important non-empty columns that cannot be represented by the current project/license/risk schema or by a clear import warning.
4. Tests reveal the project lookup can return wrong context.
5. A task requires adding anything listed under "Not in v1".
