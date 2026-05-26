from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from legal_mcp.query_plan import PlanValidationResult, QueryPlan


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
        domain = self.domains.get(plan.domain)
        if domain is None:
            return PlanValidationResult(False, "unsupported_domain", "query domain is not registered")
        if plan.operation not in {"lookup", "search", "list", "aggregate"}:
            return PlanValidationResult(False, "unsupported_operation", "query operation is not supported")
        if not isinstance(plan.limit, int) or plan.limit < 0 or plan.limit > 100:
            return PlanValidationResult(False, "invalid_limit", "query limit must be between 0 and 100")
        if "*" in plan.return_fields:
            return PlanValidationResult(False, "wildcard_fields_not_allowed", "return fields must be explicit")
        unknown_returns = sorted(set(plan.return_fields) - domain.fields)
        if unknown_returns:
            return PlanValidationResult(
                False,
                "unknown_return_field",
                f"return fields are not registered: {', '.join(unknown_returns)}",
            )
        allowed_filter_fields = domain.fields | domain.relationship_filter_fields
        unknown_filters = sorted({query_filter.field for query_filter in plan.filters} - allowed_filter_fields)
        if unknown_filters:
            return PlanValidationResult(
                False,
                "unknown_filter_field",
                f"filter fields are not registered: {', '.join(unknown_filters)}",
            )
        return PlanValidationResult(True)


DOMAIN_TABLES = {
    "project": "projects",
    "contract": "contracts",
    "license": "licenses",
    "risk": "risks",
}

IDENTITY_FIELDS = {
    "project": {"project_code", "name"},
    "contract": {"contract_number", "title"},
    "license": {"license_type", "identifier"},
    "risk": {"external_key", "description"},
}

FIELD_ALIASES = {
    "project": {
        "项目代号": "project_code",
        "项目名称": "name",
        "游戏名称": "name",
        "官网": "website",
        "法务BP": "legal_bp",
    },
    "contract": {
        "合同号": "contract_number",
        "合同主题": "title",
        "相对方": "counterparty",
        "我方签约公司": "company_entity",
        "金额": "total_amount",
    },
    "license": {
        "资质类型": "license_type",
        "商标": "license_type",
        "商标权利人": "rights_holder",
        "在哪家公司": "rights_holder",
        "著作权人": "copyright_holder",
        "实际运营方": "actual_operator",
        "实际运营主体": "actual_operator",
        "运营主体": "operating_entity",
    },
    "risk": {
        "风险": "description",
        "风险状态": "status",
    },
}


def build_query_catalog(conn: sqlite3.Connection) -> QueryCatalog:
    domains: dict[str, DomainCatalog] = {}
    for domain, table in DOMAIN_TABLES.items():
        fields = _table_fields(conn, table)
        relationship_filter_fields = {"project_code", "name"} if domain in {"contract", "license", "risk"} else set()
        domains[domain] = DomainCatalog(
            domain=domain,
            table=table,
            fields=fields,
            identity_fields=IDENTITY_FIELDS.get(domain, set()) & fields,
            field_aliases={
                alias: field
                for alias, field in FIELD_ALIASES.get(domain, {}).items()
                if field in fields
            },
            relationship_filter_fields=relationship_filter_fields,
        )
    return QueryCatalog(domains=domains)


def catalog_context_for_prompt(catalog: QueryCatalog) -> str:
    payload = {
        domain: {
            "fields": sorted(domain_catalog.fields),
            "identity_fields": sorted(domain_catalog.identity_fields),
            "field_aliases": domain_catalog.field_aliases,
            "relationship_filter_fields": sorted(domain_catalog.relationship_filter_fields),
        }
        for domain, domain_catalog in sorted(catalog.domains.items())
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _table_fields(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"pragma table_info({table})").fetchall()
    excluded = {"id", "project_id", "created_at", "updated_at"}
    return {str(row["name"]) for row in rows if str(row["name"]) not in excluded}
