from __future__ import annotations

from legal_mcp.tool_catalog import CATALOG, ToolCapability, tool_definitions


def test_catalog_entries_have_machine_readable_capabilities() -> None:
    get_project = CATALOG["get_project_fields"]

    assert isinstance(get_project, ToolCapability)
    assert get_project.data_domain == "project"
    assert get_project.operation == "read"
    assert "website" in get_project.return_fields
    assert get_project.requires_project_scope is True


def test_tool_definitions_include_catalog_metadata() -> None:
    definitions = tool_definitions()
    names = {tool["name"] for tool in definitions}
    resolve_project = next(
        tool for tool in definitions if tool["name"] == "resolve_project"
    )
    get_project = next(
        tool for tool in definitions if tool["name"] == "get_project_fields"
    )
    list_licenses = next(
        tool for tool in definitions if tool["name"] == "list_project_licenses"
    )

    assert "describe_my_access" in names
    assert "permissions" in resolve_project["description"]
    assert get_project["x-legal-mcp"]["data_domain"] == "project"
    assert "website" in get_project["x-legal-mcp"]["return_fields"]
    assert list_licenses["x-legal-mcp"]["data_domain"] == "license"
    assert "actual_operator" in list_licenses["x-legal-mcp"]["return_fields"]
