create table if not exists schema_version (
  id integer primary key check (id = 1),
  version integer not null,
  updated_at text not null default (datetime('now'))
);

insert into schema_version (id, version)
values (1, 13)
on conflict(id) do update set
  version = excluded.version,
  updated_at = datetime('now');

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
  handler text,
  payment_terms text,
  currency text,
  total_amount text,
  expiry_date text,
  counterparty text,
  company_entity text,
  signed_date text,
  contract_number text,
  income_expense_type text,
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

create table if not exists user_groups (
  id integer primary key,
  name text not null unique,
  description text,
  created_at text not null default (datetime('now')),
  updated_at text not null default (datetime('now'))
);

create table if not exists user_group_memberships (
  id integer primary key,
  user_id integer not null references users(id),
  group_id integer not null references user_groups(id),
  created_at text not null default (datetime('now')),
  unique(user_id, group_id)
);

create table if not exists permission_grants (
  id integer primary key,
  group_id integer not null references user_groups(id),
  operation text not null,
  data_domain text not null,
  field_name text,
  project_id integer references projects(id),
  allowed integer not null default 1 check (allowed in (0, 1)),
  created_at text not null default (datetime('now')),
  unique(group_id, operation, data_domain, field_name, project_id)
);

create table if not exists project_aliases (
  id integer primary key,
  project_id integer not null references projects(id),
  alias text not null unique,
  source text,
  created_at text not null default (datetime('now')),
  updated_at text not null default (datetime('now'))
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
  record_id integer,
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
create index if not exists idx_user_group_memberships_user_id on user_group_memberships(user_id);
create index if not exists idx_permission_grants_group_id on permission_grants(group_id);
create index if not exists idx_project_aliases_project_id on project_aliases(project_id);
create index if not exists idx_admin_sessions_user_id on admin_sessions(user_id);
create index if not exists idx_audit_events_timestamp on audit_events(timestamp);
create index if not exists idx_audit_events_user_id on audit_events(user_id);
create index if not exists idx_audit_events_tool_name on audit_events(tool_name);
create index if not exists idx_audit_disclosures_audit_event_id on audit_disclosures(audit_event_id);
create index if not exists idx_audit_disclosures_project_id on audit_disclosures(project_id);
