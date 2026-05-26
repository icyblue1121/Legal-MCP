from __future__ import annotations

from pathlib import Path

from legal_mcp import db
from legal_mcp.query_catalog import build_query_catalog, catalog_context_for_prompt
from legal_mcp.query_plan import QueryFilter, QueryPlan


def test_query_catalog_reads_registered_fields_from_sqlite_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        catalog = build_query_catalog(conn)
    finally:
        conn.close()

    assert "project" in catalog.domains
    assert "license" in catalog.domains
    assert "rights_holder" in catalog.domains["license"].fields
    assert catalog.domains["license"].field_aliases["商标权利人"] == "rights_holder"
    assert catalog.domains["license"].relationship_filter_fields == {"project_code", "name"}


def test_catalog_context_for_prompt_contains_schema_not_tools(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        context = catalog_context_for_prompt(build_query_catalog(conn))
    finally:
        conn.close()

    assert "license" in context
    assert "rights_holder" in context
    assert "get_project_fields" not in context
    assert "database handle" not in context


def test_query_catalog_validates_child_project_identity_filter(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        catalog = build_query_catalog(conn)
    finally:
        conn.close()

    plan = QueryPlan(
        domain="license",
        operation="search",
        filters=[
            QueryFilter(field="project_code", operator="eq", value="Mgame"),
            QueryFilter(field="license_type", operator="eq", value="trademark_right"),
        ],
        return_fields=["license_type", "rights_holder"],
        limit=20,
    )

    assert catalog.validate_plan(plan).ok


def test_query_catalog_rejects_unregistered_domain(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
    try:
        catalog = build_query_catalog(conn)
    finally:
        conn.close()

    plan = QueryPlan(
        domain="sqlite_master",
        operation="search",
        filters=[],
        return_fields=["sql"],
        limit=20,
    )

    result = catalog.validate_plan(plan)
    assert not result.ok
    assert result.error_code == "unsupported_domain"
