# TODOs

## GUI upload and edit entrypoint

**What:** Add a Web GUI for uploading, reviewing, and editing legal project data.

**Why:** Non-technical legal users cannot maintain production data through CSV/XLSX files and command-line imports forever.

**Pros:** Lowers adoption friction, enables team usage, and creates a cleaner path for future upload/edit workflows.

**Cons:** Adds authentication, edit conflict handling, form validation, deployment, and support complexity.

**Context:** v1 intentionally defers the Web UI. The first product proof is a local stdio MCP server backed by canonical SQLite, with CSV/XLSX import handled through a shared validation pipeline. When the GUI is built, it must reuse the same validation/import/upsert layer instead of creating a second data path.

**Depends on / blocked by:** Complete v1 MCP query validation with real legal project data and confirm users get value from AI desktop clients querying the context.

## Docker and intranet HTTP deployment

**What:** Add Docker packaging and an HTTP-based intranet deployment mode.

**Why:** Once the tool moves from individual local trial to team usage, a local stdio process is not enough for centralized data, rollout, and operations.

**Pros:** Enables shared deployment, shared database access, centralized upgrades, and enterprise-friendly operations.

**Cons:** Adds HTTP transport, authentication, Origin validation, port management, service monitoring, and deployment support.

**Context:** v1 uses local stdio MCP plus one-line install to validate the core value quickly across desktop AI clients. Docker/HTTP is the natural next step for team deployment, but including it in v1 would slow down the first proof.

**v1.1 status:** Selected as the next implementation milestone after successful real-project MCP query validation.

**Depends on / blocked by:** v1 runs successfully for at least one or two real local users, and the team confirms shared legal context data is needed.

## OCR, PDF, and historical contract extraction

**What:** Add OCR/PDF parsing and automated extraction for historical contracts and legal risk memos.

**Why:** Long-term value depends on turning existing legal archives into queryable context instead of relying forever on manual or AI-assisted CSV preparation.

**Pros:** Reduces data entry cost, scales context coverage, and moves the product closer to the long-term context engine vision.

**Cons:** Adds document parsing, Chinese OCR, contract field extraction, source citation, confidence handling, and human review complexity.

**Context:** v1 is limited to structured CSV/XLSX import and MCP querying. Automated extraction should wait until the field model and real query patterns are validated with a small set of real projects.

**Depends on / blocked by:** Import three to five real legal projects in v1 and learn which fields are actually used by AI clients and legal users.

## OA, Feishu, and CLM connectors

**What:** Add connectors for OA, Feishu, CLM, or other enterprise legal data systems.

**Why:** Enterprise legal context ultimately lives across multiple systems, and the product cannot rely on manual exports forever.

**Pros:** Keeps context fresher, reduces manual data movement, and moves closer to the real enterprise workflow.

**Cons:** Each connector adds permissions, field mapping, API limits, sync failures, audit boundaries, and vendor-specific support load.

**Context:** v1 does not replace existing systems. It imports structured data so desktop AI clients can query legal context. Connector priority should be decided after the first real usage cycle identifies which source system matters most.

**Depends on / blocked by:** v1 real usage clarifies the next highest-value data source: OA, Feishu sheets, CLM, or shared file storage.

## Enterprise permissions and audit console

**What:** Add enterprise-grade permissions, multi-user access control, and an audit console.

**Why:** Legal data is sensitive. Team deployments need clear control over who can query which data, who imported or edited records, and what each AI client accessed.

**Pros:** Supports enterprise procurement, security review, internal compliance, and responsibility tracking.

**Cons:** Adds user accounts, roles, permission boundaries, audit UI, log retention policy, and operational support.

**v1.2 status:** Implemented local users, per-user API keys, project-level
access grants, DB-backed disclosure audit, and a lightweight Admin Web UI for
user, grant, key, and audit review workflows.

**Post-v1.2:** Field-level permissions and SSO remain future enterprise work.
