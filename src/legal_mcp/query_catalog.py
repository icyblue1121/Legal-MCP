from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from legal_mcp.query_plan import (
    SUPPORTED_OPERATIONS,
    SUPPORTED_OPERATORS,
    PlanValidationResult,
    QueryPlan,
    validate_query_plan,
)
from legal_mcp.tool_catalog import CONTRACT_FIELDS, LICENSE_FIELDS, PROJECT_FIELDS

# Fields a cross-domain search may return. The cross_domain executor builds its
# own per-domain return lists, but model plans must still declare return fields
# from this whitelist so validation can approve them.
CROSS_DOMAIN_RETURN_FIELDS = frozenset(
    {
        "project_code",
        "name",
        "contract_number",
        "title",
        "counterparty",
        "license_type",
        "actual_operator",
        "operating_entity",
    }
)
# A cross-domain plan filters by a single free-text term.
CROSS_DOMAIN_FILTER_FIELDS = frozenset({"q", "query", "term"})


@dataclass(frozen=True)
class DomainCatalog:
    domain: str
    table: str
    fields: set[str]
    identity_fields: set[str]
    field_aliases: dict[str, str] = field(default_factory=dict)
    relationship_filter_fields: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class QueryCatalog:
    domains: dict[str, DomainCatalog]

    def validate_plan(self, plan: QueryPlan) -> PlanValidationResult:
        # Structure and enum checks live in one place (query_plan), so the graph
        # validate_plan node and classify_question agree with this validator.
        structural = validate_query_plan(plan)
        if not structural.ok:
            return structural

        domain = self.domains.get(plan.domain)
        if domain is None:
            return PlanValidationResult(
                False, "unsupported_domain", "query domain is not registered"
            )

        unknown_returns = sorted(set(plan.return_fields) - domain.fields)
        if unknown_returns:
            return PlanValidationResult(
                False,
                "unknown_return_field",
                f"return fields are not registered: {', '.join(unknown_returns)}",
            )

        allowed_filter_fields = domain.fields | domain.relationship_filter_fields
        unknown_filters = sorted(
            {query_filter.field for query_filter in plan.filters} - allowed_filter_fields
        )
        if unknown_filters:
            return PlanValidationResult(
                False,
                "unknown_filter_field",
                f"filter fields are not registered: {', '.join(unknown_filters)}",
            )
        return PlanValidationResult(True)

    def resolve_field(self, domain: str, name: str) -> str | None:
        """Resolve an alias or canonical field name to a registered field."""
        domain_catalog = self.domains.get(domain)
        if domain_catalog is None:
            return None
        if name in domain_catalog.fields:
            return name
        if name in domain_catalog.relationship_filter_fields:
            return name
        alias_target = domain_catalog.field_aliases.get(name)
        if alias_target is not None:
            return alias_target
        return None


# Domains backed by a real table. Must stay aligned with the domains
# search_tools.execute_search_plan can execute. (risk is intentionally not
# registered yet: there is no risk executor.)
DOMAIN_FIELDS = {
    "project": frozenset(PROJECT_FIELDS),
    "contract": frozenset(CONTRACT_FIELDS),
    "license": frozenset(LICENSE_FIELDS),
}

DOMAIN_TABLES = {
    "project": "projects",
    "contract": "contracts",
    "license": "licenses",
}

IDENTITY_FIELDS = {
    "project": {"project_code", "name"},
    "contract": {"contract_number", "title"},
    "license": {"license_type", "identifier"},
}

FIELD_ALIASES = {
    "project": {
        "项目代号": "project_code",
        "项目名称": "name",
        "游戏名称": "name",
        "官网": "website",
        "法务BP": "legal_bp",
        "发行团队": "release_team",
        "所属部门": "department",
        "联系人": "contact_person",
        "对接人": "contact_person",
        "上线状态": "stage",
        "阶段": "stage",
        "备注": "notes",
    },
    "contract": {
        "合同号": "contract_number",
        "合同主题": "title",
        "相对方": "counterparty",
        "我方签约公司": "company_entity",
        "金额": "total_amount",
        "经办人": "handler",
    },
    "license": {
        "资质类型": "license_type",
        "商标": "license_type",
        "商标权利人": "rights_holder",
        "在哪家公司": "rights_holder",
        "著作权人": "copyright_holder",
        "实际运营方": "actual_operator",
        "实际运营主体": "actual_operator",
        "运营方": "actual_operator",
        "运营单位": "operating_entity",
        "运营主体": "operating_entity",
    },
}


def build_query_catalog(conn: sqlite3.Connection) -> QueryCatalog:
    # Fields are taken from tool_catalog (the same source the executor's column
    # maps use) so a plan that validates can always execute. The connection is
    # accepted for API compatibility and to optionally intersect with live
    # columns.
    live_columns = {
        domain: _table_fields(conn, table) for domain, table in DOMAIN_TABLES.items()
    }
    domains: dict[str, DomainCatalog] = {}
    for domain, canonical_fields in DOMAIN_FIELDS.items():
        fields = set(canonical_fields) & live_columns.get(domain, set(canonical_fields))
        if not fields:
            # If introspection found nothing (e.g. a stub db), trust the catalog.
            fields = set(canonical_fields)
        relationship_filter_fields = (
            {"project_code", "name"} if domain in {"contract", "license"} else set()
        )
        domains[domain] = DomainCatalog(
            domain=domain,
            table=DOMAIN_TABLES[domain],
            fields=fields,
            identity_fields=IDENTITY_FIELDS.get(domain, set()) & fields,
            field_aliases={
                alias: target
                for alias, target in FIELD_ALIASES.get(domain, {}).items()
                if target in fields
            },
            relationship_filter_fields=relationship_filter_fields,
        )

    domains["cross_domain"] = DomainCatalog(
        domain="cross_domain",
        table="",
        fields=set(CROSS_DOMAIN_RETURN_FIELDS),
        identity_fields=set(),
        field_aliases={},
        relationship_filter_fields=set(CROSS_DOMAIN_FILTER_FIELDS),
    )
    return QueryCatalog(domains=domains)


def catalog_context_for_prompt(catalog: QueryCatalog) -> str:
    payload: dict[str, object] = {
        "supported_operations": sorted(SUPPORTED_OPERATIONS),
        "supported_operators": sorted(SUPPORTED_OPERATORS),
        "filter_shape": {"field": "<field>", "operator": "<operator>", "value": "<value>"},
        "cross_domain_usage": (
            "Use domain 'cross_domain' for free-text searches that span projects, "
            "contracts, and licenses. Provide exactly one filter with field 'q', "
            "operator 'contains', and the search term as value."
        ),
        "domains": {
            domain: {
                "fields": sorted(domain_catalog.fields),
                "identity_fields": sorted(domain_catalog.identity_fields),
                "field_aliases": domain_catalog.field_aliases,
                "relationship_filter_fields": sorted(domain_catalog.relationship_filter_fields),
            }
            for domain, domain_catalog in sorted(catalog.domains.items())
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _table_fields(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"pragma table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    excluded = {"id", "project_id", "created_at", "updated_at"}
    return {str(row["name"]) for row in rows if str(row["name"]) not in excluded}
