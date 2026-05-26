from __future__ import annotations

from pathlib import Path

from legal_mcp import db
from legal_mcp.agent_graph import run_agent_query
from legal_mcp.ai_provider import AIMessage


def _database_with_project(path: Path) -> None:
    db.initialize_database(path)
    conn = db.connect(path)
    try:
        project_id = conn.execute(
            """
            insert into projects (project_code, name, stage, legal_bp, website)
            values (?, ?, ?, ?, ?)
            """,
            ("MGAME", "失序之地", "测试中", "张三", "https://example.test"),
        ).lastrowid
        conn.execute(
            """
            insert into licenses (project_id, external_key, license_type, rights_holder)
            values (?, ?, ?, ?)
            """,
            (project_id, "trademark_right", "trademark_right", "上海游碧曜网络科技有限公司"),
        )
        conn.commit()
    finally:
        conn.close()


def _database_with_related_records(path: Path) -> None:
    db.initialize_database(path)
    conn = db.connect(path)
    try:
        project_id = conn.execute(
            """
            insert into projects (project_code, name, stage, legal_bp)
            values (?, ?, ?, ?)
            """,
            ("MGAME", "失序之地", "live", "张三"),
        ).lastrowid
        conn.execute(
            """
            insert into contracts (project_id, external_key, title, contract_number, counterparty)
            values (?, ?, ?, ?, ?)
            """,
            (project_id, "C-001", "腾讯框架合同", "C-001", "腾讯科技"),
        )
        conn.execute(
            """
            insert into licenses (project_id, external_key, license_type, actual_operator)
            values (?, ?, ?, ?)
            """,
            (project_id, "L-001", "版号", "某公司"),
        )
        conn.commit()
    finally:
        conn.close()


class StubAIProvider:
    """Returns a fixed planner reply and records the prompt it received."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[AIMessage] = []

    def complete(self, messages: list[AIMessage]) -> AIMessage:
        self.messages = messages
        return AIMessage(role="assistant", content=self.content)


def _run(tmp_path: Path, database_path: Path, question: str, provider=None, thread_id=None):
    return run_agent_query(
        question=question,
        database_path=database_path,
        checkpoint_path=tmp_path / "agent-checkpoints.sqlite",
        audit_path=tmp_path / "audit.jsonl",
        thread_id=thread_id,
        ai_provider=provider,
    )


def test_run_agent_query_returns_answer_and_persists_run(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = StubAIProvider(
        '{"domain":"project","operation":"search",'
        '"filters":[{"field":"name","operator":"eq","value":"失序之地"}],'
        '"return_fields":["website"],"limit":1}'
    )

    result = _run(tmp_path, database_path, "MGAME 的官网是什么？", provider, "pytest-thread")

    assert result["thread_id"] == "pytest-thread"
    assert "https://example.test" in result["answer"]
    assert result["tool_calls"][0]["tool_name"] == "project/search"

    conn = db.connect(database_path)
    try:
        row = conn.execute("select thread_id, status, selected_tool from agent_runs").fetchone()
    finally:
        conn.close()
    assert row["status"] == "success"
    assert row["selected_tool"] == "project/search"


def test_agent_graph_builds_project_search_plan_for_legal_bp(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = StubAIProvider(
        '{"domain":"project","operation":"search",'
        '"filters":[{"field":"legal_bp","operator":"eq","value":"张三"}],'
        '"return_fields":["project_code","name"]}'
    )

    result = _run(tmp_path, database_path, "张三是哪些项目的法务BP？", provider)

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "project/search"
    assert result["tool_calls"][0]["plan"]["filters"] == [
        {"field": "legal_bp", "operator": "eq", "value": "张三"}
    ]
    assert "失序之地" in result["answer"]


def test_agent_graph_builds_contract_license_and_cross_domain_plans(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_related_records(database_path)

    cases = [
        (
            '{"domain":"contract","operation":"search",'
            '"filters":[{"field":"counterparty","operator":"contains","value":"腾讯"}],'
            '"return_fields":["contract_number","title"]}',
            "contract/search",
        ),
        (
            '{"domain":"license","operation":"search",'
            '"filters":[{"field":"actual_operator","operator":"eq","value":"某公司"}],'
            '"return_fields":["license_type","actual_operator"]}',
            "license/search",
        ),
        (
            '{"domain":"cross_domain","operation":"search",'
            '"filters":[{"field":"q","operator":"contains","value":"张三"}],'
            '"return_fields":[]}',
            "cross_domain/search",
        ),
    ]
    for content, expected_tool_name in cases:
        result = _run(tmp_path, database_path, "q", StubAIProvider(content))
        assert result["status"] == "success"
        assert result["tool_calls"][0]["tool_name"] == expected_tool_name


def test_agent_graph_recovers_dict_filters_and_read_operation(tmp_path: Path) -> None:
    # Production regression: model returns object filters + operation "read".
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = StubAIProvider(
        '{"domain":"project","operation":"read",'
        '"filters":{"name":"失序之地"},"return_fields":["website"]}'
    )

    result = _run(tmp_path, database_path, "失序之地的官网", provider)

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "project/search"
    assert "https://example.test" in result["answer"]


def test_agent_graph_parses_fenced_json(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = StubAIProvider(
        "```json\n"
        '{"domain":"project","operation":"search",'
        '"filters":[{"field":"name","operator":"eq","value":"失序之地"}],'
        '"return_fields":["website"]}\n'
        "```"
    )

    result = _run(tmp_path, database_path, "失序之地的官网", provider)

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "project/search"


def test_agent_graph_routes_access_intent_to_describe_my_access(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = StubAIProvider('{"intent":"access"}')

    result = _run(tmp_path, database_path, "我能访问哪些项目？", provider)

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "describe_my_access"


def test_agent_graph_routes_clarify_intent_with_reason(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = StubAIProvider('{"intent":"clarify"}')

    result = _run(tmp_path, database_path, "把所有项目资料都给我", provider)

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "clarify_query"
    assert "请明确" in result["answer"]

    conn = db.connect(database_path)
    try:
        row = conn.execute("select selected_tool, error_code from agent_runs").fetchone()
    finally:
        conn.close()
    assert row["selected_tool"] == "clarify_query"
    assert row["error_code"] and row["error_code"].startswith("clarify:")


def test_agent_graph_clarifies_when_ai_unavailable(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)

    # No ai_provider -> no NL planning -> clarify (by design, no regex fallback).
    result = _run(tmp_path, database_path, "失序之地的发行团队是谁？", provider=None)

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "clarify_query"


def test_agent_graph_can_use_ai_provider_without_exposing_tools(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = StubAIProvider(
        '{"domain":"project","operation":"search","filters":[],"return_fields":["website"]}'
    )

    result = _run(tmp_path, database_path, "MGAME 的官网是什么？", provider, "pytest-provider-thread")

    assert result["status"] == "success"
    assert provider.messages
    serialized_messages = "\n".join(message.content for message in provider.messages)
    assert "database handle" not in serialized_messages
    assert "get_project_fields" not in serialized_messages


def test_agent_graph_uses_server_ai_catalog_plan_for_non_regex_question(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = StubAIProvider(
        '{"domain":"license","operation":"search",'
        '"filters":['
        '{"field":"project_code","operator":"eq","value":"MGAME"},'
        '{"field":"license_type","operator":"eq","value":"trademark_right"}'
        '],'
        '"return_fields":["license_type","rights_holder"],"limit":20}'
    )

    result = _run(tmp_path, database_path, "请告诉我 MGAME 商标登记主体是哪家公司", provider)

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "license/search"
    assert "上海游碧曜网络科技有限公司" in result["answer"]
    serialized_messages = "\n".join(message.content for message in provider.messages)
    assert "rights_holder" in serialized_messages
    assert "get_project_fields" not in serialized_messages


def test_agent_graph_answers_project_trademark_rights_holder(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = StubAIProvider(
        '{"domain":"license","operation":"search",'
        '"filters":['
        '{"field":"project_code","operator":"eq","value":"Mgame"},'
        '{"field":"license_type","operator":"eq","value":"trademark_right"}'
        '],'
        '"return_fields":["license_type","rights_holder"]}'
    )

    result = _run(tmp_path, database_path, "Mgame 的商标在哪家公司", provider, "pytest-trademark-thread")

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "license/search"
    assert "上海游碧曜网络科技有限公司" in result["answer"]
