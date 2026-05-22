create table if not exists projects (
  id integer primary key,
  project_code text not null unique,
  name text not null,
  stage text not null,
  legal_bp text,
  department text,
  release_team text,
  contact_person text,
  website text,
  notes text,
  created_at text not null default (datetime('now')),
  updated_at text not null default (datetime('now'))
);

create table if not exists contracts (
  id integer primary key,
  project_id integer not null references projects(id),
  external_key text not null,
  title text not null,
  counterparty text,
  signed_date text,
  summary text,
  created_at text not null default (datetime('now')),
  updated_at text not null default (datetime('now')),
  unique(project_id, external_key)
);

create table if not exists licenses (
  id integer primary key,
  project_id integer not null references projects(id),
  external_key text not null,
  license_type text not null,
  identifier text,
  entity_name text,
  issuer text,
  approval_number text,
  rights_holder text,
  copyright_holder text,
  operating_entity text,
  actual_operator text,
  authorization_relation text,
  expiry_date text,
  notes text,
  created_at text not null default (datetime('now')),
  updated_at text not null default (datetime('now')),
  unique(project_id, external_key)
);

create table if not exists risks (
  id integer primary key,
  project_id integer not null references projects(id),
  external_key text not null,
  description text not null,
  status text not null,
  source text,
  created_at text not null default (datetime('now')),
  updated_at text not null default (datetime('now')),
  unique(project_id, external_key)
);

create table if not exists users (
  id integer primary key,
  email text not null unique,
  display_name text not null,
  role text not null check (role in ('admin', 'legal', 'business', 'auditor')),
  status text not null default 'active' check (status in ('active', 'disabled')),
  password_hash text,
  external_subject text,
  created_at text not null default (datetime('now')),
  updated_at text not null default (datetime('now'))
);

create table if not exists api_keys (
  id integer primary key,
  user_id integer not null references users(id),
  key_prefix text not null,
  key_hash text not null,
  label text not null,
  status text not null default 'active' check (status in ('active', 'revoked')),
  last_used_at text,
  created_at text not null default (datetime('now')),
  revoked_at text
);

create table if not exists project_access (
  id integer primary key,
  user_id integer not null references users(id),
  project_id integer not null references projects(id),
  granted_by_user_id integer not null references users(id),
  created_at text not null default (datetime('now')),
  unique(user_id, project_id)
);

create table if not exists admin_sessions (
  id integer primary key,
  user_id integer not null references users(id),
  session_hash text not null unique,
  expires_at text not null,
  created_at text not null default (datetime('now'))
);

create table if not exists audit_events (
  id integer primary key,
  timestamp text not null default (datetime('now')),
  user_id integer references users(id),
  api_key_id integer references api_keys(id),
  source_client text,
  tool_name text not null,
  rationale text,
  arguments_summary text not null,
  result_status text not null,
  error_code text,
  response_record_count integer not null default 0
);

create table if not exists audit_disclosures (
  id integer primary key,
  audit_event_id integer not null references audit_events(id),
  project_id integer references projects(id),
  record_type text not null,
  record_id integer not null,
  decision text not null check (decision in ('allowed', 'denied')),
  reason text not null
);

create index if not exists idx_projects_stage on projects(stage);
create index if not exists idx_projects_name on projects(name);
create index if not exists idx_licenses_license_type on licenses(license_type);
create index if not exists idx_licenses_expiry_date on licenses(expiry_date);
create index if not exists idx_risks_status on risks(status);
create index if not exists idx_risks_project_status on risks(project_id, status);
create index if not exists idx_users_external_subject on users(external_subject);
create index if not exists idx_api_keys_key_prefix on api_keys(key_prefix);
create index if not exists idx_api_keys_user_id on api_keys(user_id);
create index if not exists idx_project_access_project_id on project_access(project_id);
create index if not exists idx_admin_sessions_user_id on admin_sessions(user_id);
create index if not exists idx_audit_events_timestamp on audit_events(timestamp);
create index if not exists idx_audit_events_user_id on audit_events(user_id);
create index if not exists idx_audit_events_tool_name on audit_events(tool_name);
create index if not exists idx_audit_disclosures_audit_event_id on audit_disclosures(audit_event_id);
create index if not exists idx_audit_disclosures_project_id on audit_disclosures(project_id);
