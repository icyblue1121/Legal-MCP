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


def test_run_agent_query_returns_answer_and_persists_run(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    checkpoint_path = tmp_path / "agent-checkpoints.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    _database_with_project(database_path)

    result = run_agent_query(
        question="MGAME 的官网是什么？",
        database_path=database_path,
        checkpoint_path=checkpoint_path,
        audit_path=audit_path,
        thread_id="pytest-thread",
    )

    assert result["thread_id"] == "pytest-thread"
    assert "https://example.test" in result["answer"]
    assert result["tool_calls"][0]["tool_name"] == "project/lookup"
    assert checkpoint_path.exists()

    conn = db.connect(database_path)
    try:
        row = conn.execute(
            "select thread_id, status, selected_tool from agent_runs"
        ).fetchone()
    finally:
        conn.close()
    assert row["thread_id"] == "pytest-thread"
    assert row["status"] == "success"
    assert row["selected_tool"] == "project/lookup"


def test_agent_graph_builds_project_search_plan_for_legal_bp(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)

    result = run_agent_query(
        question="张三是哪些项目的法务BP？",
        database_path=database_path,
        checkpoint_path=tmp_path / "agent-checkpoints.sqlite",
        audit_path=tmp_path / "audit.jsonl",
        thread_id="pytest-search-thread",
    )

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "project/search"
    assert result["tool_calls"][0]["plan"]["filters"] == [
        {"field": "legal_bp", "operator": "eq", "value": "张三"}
    ]
    assert "失序之地" in result["answer"]


def test_agent_graph_builds_contract_license_and_cross_domain_plans(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    db.initialize_database(database_path)
    conn = db.connect(database_path)
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

    cases = [
        ("哪些合同的相对方包含腾讯？", "contract/search"),
        ("某公司是哪些资质的实际运营方？", "license/search"),
        ("张三关联哪些资料？", "cross_domain/search"),
    ]
    for question, expected_tool_name in cases:
        result = run_agent_query(
            question=question,
            database_path=database_path,
            checkpoint_path=tmp_path / f"{expected_tool_name.replace('/', '-')}.sqlite",
            audit_path=tmp_path / "audit.jsonl",
        )

        assert result["status"] == "success"
        assert result["tool_calls"][0]["tool_name"] == expected_tool_name


def test_agent_graph_routes_ambiguous_questions_to_clarification(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)

    result = run_agent_query(
        question="把所有项目资料都给我",
        database_path=database_path,
        checkpoint_path=tmp_path / "agent-checkpoints.sqlite",
        audit_path=tmp_path / "audit.jsonl",
    )

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "clarify_query"
    assert "请明确" in result["answer"]


class FakeAIProvider:
    def __init__(self) -> None:
        self.messages: list[AIMessage] = []

    def complete(self, messages: list[AIMessage]) -> AIMessage:
        self.messages = messages
        return AIMessage(
            role="assistant",
            content='{"domain":"project","operation":"search","filters":[]}',
        )


def test_agent_graph_can_use_ai_provider_without_exposing_tools(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = FakeAIProvider()

    result = run_agent_query(
        question="MGAME 的官网是什么？",
        database_path=database_path,
        checkpoint_path=tmp_path / "agent-checkpoints.sqlite",
        audit_path=tmp_path / "audit.jsonl",
        thread_id="pytest-provider-thread",
        ai_provider=provider,
    )

    assert result["status"] == "success"
    assert provider.messages
    serialized_messages = "\n".join(message.content for message in provider.messages)
    assert "database handle" not in serialized_messages


class FakeCatalogAIProvider:
    def __init__(self) -> None:
        self.messages: list[AIMessage] = []

    def complete(self, messages: list[AIMessage]) -> AIMessage:
        self.messages = messages
        return AIMessage(
            role="assistant",
            content=(
                '{"domain":"license","operation":"search",'
                '"filters":['
                '{"field":"project_code","operator":"eq","value":"MGAME"},'
                '{"field":"license_type","operator":"eq","value":"trademark_right"}'
                '],'
                '"return_fields":["license_type","rights_holder"],'
                '"limit":20}'
            ),
        )


def test_agent_graph_uses_server_ai_catalog_plan_for_non_regex_question(tmp_path: Path) -> None:
    database_path = tmp_path / "legal.db"
    _database_with_project(database_path)
    provider = FakeCatalogAIProvider()

    result = run_agent_query(
        question="请告诉我 MGAME 商标登记主体是哪家公司",
        database_path=database_path,
        checkpoint_path=tmp_path / "agent-checkpoints.sqlite",
        audit_path=tmp_path / "audit.jsonl",
        ai_provider=provider,
    )

    assert result["status"] == "success"
    assert result["tool_calls"][0]["tool_name"] == "license/search"
    assert "上海游碧曜网络科技有限公司" in result["answer"]
    serialized_messages = "\n".join(message.content for message in provider.messages)
    assert "rights_holder" in serialized_messages
    assert "get_project_fields" not in serialized_messages
    assert "get_project_fields" not in serialized_messages
