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

create index if not exists idx_projects_stage on projects(stage);
create index if not exists idx_projects_name on projects(name);
create index if not exists idx_licenses_license_type on licenses(license_type);
create index if not exists idx_licenses_expiry_date on licenses(expiry_date);
create index if not exists idx_risks_status on risks(status);
create index if not exists idx_risks_project_status on risks(project_id, status);
