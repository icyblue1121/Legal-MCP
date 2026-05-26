from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypedDict

from legal_mcp import db
from legal_mcp.agent_observability import build_trace_metadata, flush_langfuse, langfuse_callbacks
from legal_mcp.agent_router import (
    clarify_result,
    query_plan_from_model_intent,
)
from legal_mcp.audit import DEFAULT_AUDIT_PATH
from legal_mcp.ai_provider import AIMessage, AIProvider
from legal_mcp.policy import AccessContext
from legal_mcp.query_authorization import authorize_query_plan
from legal_mcp.query_catalog import QueryCatalog, build_query_catalog, catalog_context_for_prompt
from legal_mcp.query_plan import QueryFilter, QueryPlan
from legal_mcp.search_tools import execute_search_plan
from legal_mcp.tools_access import describe_my_access


class AgentState(TypedDict, total=False):
    question: str
    query_type: str
    normalized_question: str
    query_plan: QueryPlan
    tool_result: dict[str, Any]
    answer: str
    error: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    model_intent: dict[str, Any]
    clarify_reason: str


def run_agent_query(
    *,
    question: str,
    database_path: str | Path,
    checkpoint_path: str | Path | None = None,
    audit_path: str | Path = DEFAULT_AUDIT_PATH,
    access_context: AccessContext | None = None,
    thread_id: str | None = None,
    ai_provider: AIProvider | None = None,
) -> dict[str, Any]:
    actual_thread_id = thread_id or str(uuid.uuid4())
    actual_checkpoint_path = (
        Path(checkpoint_path) if checkpoint_path else _default_checkpoint_path(database_path)
    )
    state = _run_graph(
        question=question,
        database_path=database_path,
        audit_path=audit_path,
        access_context=access_context,
        checkpoint_path=actual_checkpoint_path,
        thread_id=actual_thread_id,
        ai_provider=ai_provider,
    )
    result = _result_from_state(state, actual_thread_id)
    _record_agent_run(database_path, actual_thread_id, question, result)
    return result


def run_structured_query(
    *,
    query: dict[str, Any],
    database_path: str | Path,
    checkpoint_path: str | Path | None = None,
    audit_path: str | Path = DEFAULT_AUDIT_PATH,
    access_context: AccessContext | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    plan = _query_plan_from_payload(query)
    actual_thread_id = thread_id or str(uuid.uuid4())
    actual_checkpoint_path = (
        Path(checkpoint_path) if checkpoint_path else _default_checkpoint_path(database_path)
    )
    state = _run_graph(
        question="structured_query",
        database_path=database_path,
        audit_path=audit_path,
        access_context=access_context,
        checkpoint_path=actual_checkpoint_path,
        thread_id=actual_thread_id,
        structured_plan=plan,
    )
    result = _result_from_state(state, actual_thread_id)
    _record_agent_run(database_path, actual_thread_id, "structured_query", result)
    return result


def _result_from_state(state: AgentState, thread_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "answer": state.get("answer", ""),
        "thread_id": thread_id,
        "tool_calls": state.get("tool_calls", []),
        "status": "error" if state.get("error") else "success",
    }
    if "tool_result" in state:
        result["result"] = state["tool_result"]
    if state.get("error"):
        result["error"] = state["error"]
    return result


def _default_checkpoint_path(database_path: str | Path) -> Path:
    return Path(database_path).with_name("legal-mcp-agent-checkpoints.sqlite")


def _run_graph(
    *,
    question: str,
    database_path: str | Path,
    audit_path: str | Path,
    access_context: AccessContext | None,
    checkpoint_path: Path,
    thread_id: str,
    ai_provider: AIProvider | None = None,
    structured_plan: QueryPlan | None = None,
) -> AgentState:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return _run_linear_graph(
            question=question,
            database_path=database_path,
            audit_path=audit_path,
            access_context=access_context,
            checkpoint_path=checkpoint_path,
            thread_id=thread_id,
            ai_provider=ai_provider,
            structured_plan=structured_plan,
        )

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        checkpointer = SqliteSaver(checkpoint_conn)
        graph = _build_langgraph(
            database_path=database_path,
            audit_path=audit_path,
            access_context=access_context,
            checkpointer=checkpointer,
            state_graph_cls=StateGraph,
            start=START,
            end=END,
            ai_provider=ai_provider,
        )
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        callbacks = langfuse_callbacks()
        if callbacks:
            config["callbacks"] = callbacks
            config["metadata"] = build_trace_metadata(
                thread_id=thread_id,
                tool_name=None,
                status="started",
                user_id=(
                    str(access_context.user_id)
                    if access_context is not None and access_context.user_id is not None
                    else None
                ),
            )
        initial_state: AgentState = {"question": question}
        if structured_plan is not None:
            initial_state["query_type"] = "search"
            initial_state["query_plan"] = structured_plan
        try:
            return graph.invoke(initial_state, config)
        finally:
            if callbacks:
                flush_langfuse()
    finally:
        checkpoint_conn.close()


def _build_langgraph(
    *,
    database_path: str | Path,
    audit_path: str | Path,
    access_context: AccessContext | None,
    checkpointer: Any,
    state_graph_cls: Any,
    start: str,
    end: str,
    ai_provider: AIProvider | None = None,
) -> Any:
    workflow = state_graph_cls(AgentState)
    workflow.add_node(
        "classify_question",
        lambda state: classify_question(state, database_path, ai_provider),
    )
    workflow.add_node("normalize_query", normalize_query)
    workflow.add_node("build_query_plan", build_query_plan)
    workflow.add_node("validate_plan", lambda state: validate_plan(state, database_path))
    workflow.add_node(
        "authorize_plan",
        lambda state: authorize_plan(state, database_path, access_context),
    )
    workflow.add_node(
        "execute_plan",
        lambda state: execute_plan(state, database_path, audit_path, access_context),
    )
    workflow.add_node("format_answer", format_answer)
    workflow.add_edge(start, "classify_question")
    workflow.add_edge("classify_question", "normalize_query")
    workflow.add_edge("normalize_query", "build_query_plan")
    workflow.add_edge("build_query_plan", "validate_plan")
    workflow.add_edge("validate_plan", "authorize_plan")
    workflow.add_edge("authorize_plan", "execute_plan")
    workflow.add_edge("execute_plan", "format_answer")
    workflow.add_edge("format_answer", end)
    return workflow.compile(checkpointer=checkpointer)


def _run_linear_graph(
    *,
    question: str,
    database_path: str | Path,
    audit_path: str | Path,
    access_context: AccessContext | None,
    checkpoint_path: Path,
    thread_id: str,
    ai_provider: AIProvider | None = None,
    structured_plan: QueryPlan | None = None,
) -> AgentState:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_conn = sqlite3.connect(checkpoint_path)
    try:
        checkpoint_conn.execute(
            """
            create table if not exists agent_checkpoints (
              thread_id text not null,
              node text not null,
              state_json text not null,
              created_at text not null default (datetime('now'))
            )
            """
        )
        state: AgentState = {"question": question}
        if structured_plan is not None:
            state["query_type"] = "search"
            state["query_plan"] = structured_plan
        nodes = (
            ("classify_question", lambda: classify_question(state, database_path, ai_provider)),
            ("normalize_query", lambda: normalize_query(state)),
            ("build_query_plan", lambda: build_query_plan(state)),
            ("validate_plan", lambda: validate_plan(state, database_path)),
            ("authorize_plan", lambda: authorize_plan(state, database_path, access_context)),
            ("execute_plan", lambda: execute_plan(state, database_path, audit_path, access_context)),
            ("format_answer", lambda: format_answer(state)),
        )
        for node_name, node in nodes:
            update = node()
            state.update(update)
            checkpoint_conn.execute(
                """
                insert into agent_checkpoints (thread_id, node, state_json)
                values (?, ?, ?)
                """,
                (
                    thread_id,
                    node_name,
                    json.dumps(_checkpoint_state(state), ensure_ascii=False, sort_keys=True),
                ),
            )
        checkpoint_conn.commit()
        return state
    finally:
        checkpoint_conn.close()


def classify_question(
    state: AgentState,
    database_path: str | Path,
    ai_provider: AIProvider | None = None,
) -> dict[str, Any]:
    # A pre-supplied plan (structured_query) skips natural-language planning.
    if state.get("query_plan") is not None:
        return {"query_type": "search"}

    catalog = _catalog_for_database(database_path)
    model_intent = _model_intent(state["question"], ai_provider, catalog)

    if model_intent.get("intent") == "access":
        return {"query_type": "access", "model_intent": model_intent}
    if model_intent.get("intent") == "clarify":
        return {
            "query_type": "clarify",
            "model_intent": model_intent,
            "clarify_reason": "model could not map the question to authorized fields",
        }

    plan = query_plan_from_model_intent(model_intent, catalog) if model_intent else None
    if plan is not None:
        validation = catalog.validate_plan(plan)
        if validation.ok:
            return {"query_type": "search", "query_plan": plan, "model_intent": model_intent}
        return {
            "query_type": "clarify",
            "model_intent": model_intent,
            "clarify_reason": validation.message or validation.error_code or "invalid plan",
        }

    reason = "server AI is unavailable" if not model_intent else "model did not return a usable plan"
    update: dict[str, Any] = {"query_type": "clarify", "clarify_reason": reason}
    if model_intent:
        update["model_intent"] = model_intent
    return update


def _catalog_for_database(database_path: str | Path) -> QueryCatalog:
    conn = db.connect(database_path)
    try:
        return build_query_catalog(conn)
    finally:
        conn.close()


def _model_intent(
    question: str,
    ai_provider: AIProvider | None,
    catalog: QueryCatalog,
) -> dict[str, Any]:
    if ai_provider is None:
        return {}
    messages = [
        AIMessage(role="system", content=_planner_system_prompt(catalog)),
        AIMessage(role="user", content=question),
    ]
    # A server-side AI outage or malformed reply must not break agent_query;
    # an empty intent makes the graph clarify instead of propagating the error.
    try:
        response = ai_provider.complete(messages)
    except Exception:
        return {}
    parsed = _parse_json_object(response.content)
    return parsed if isinstance(parsed, dict) else {}


def _planner_system_prompt(catalog: QueryCatalog) -> str:
    return (
        "You are the Legal-MCP server-side query planner. Read the user question and the "
        "catalog, then return exactly one JSON object and nothing else.\n"
        "Return one of these shapes:\n"
        '  1. A data plan: {"domain": <a key of catalog.domains>, "operation": "search", '
        '"filters": [{"field": <field>, "operator": <one of supported_operators>, '
        '"value": <value>}], "return_fields": [<field>, ...], "limit": <int 1-100>}.\n'
        '  2. {"intent": "access"} if the user asks which projects or fields they can access.\n'
        '  3. {"intent": "clarify"} if the question is ambiguous or references a field that is '
        "not in the catalog.\n"
        "Rules: use only domains and canonical English field names found under catalog.domains. "
        "'filters' MUST be a JSON array of filter objects, never a bare mapping. Resolve any "
        "Chinese or alias name to its canonical field using field_aliases. Use domain "
        "'cross_domain' with a single {field:'q',operator:'contains'} filter for free-text "
        "searches that span domains. Never output SQL, table names, tool names, prose, or markdown.\n"
        "Example: question '指间山海的发行团队是谁' -> "
        '{"domain": "project", "operation": "search", '
        '"filters": [{"field": "name", "operator": "eq", "value": "指间山海"}], '
        '"return_fields": ["release_team"], "limit": 1}\n'
        f"Catalog: {catalog_context_for_prompt(catalog)}"
    )


def _parse_json_object(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        parsed = _extract_json_object(content)
    return parsed if isinstance(parsed, dict) else None


def _extract_json_object(content: str) -> dict[str, Any] | None:
    if not isinstance(content, str):
        return None
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize_query(state: AgentState) -> dict[str, Any]:
    return {"normalized_question": state["question"].strip()}


def build_query_plan(state: AgentState) -> dict[str, Any]:
    # Planning happens in classify_question (model-driven) or is supplied by
    # structured_query. This node is retained for graph-topology stability.
    return {}


def validate_plan(state: AgentState, database_path: str | Path) -> dict[str, Any]:
    plan = state.get("query_plan")
    if plan is None or state.get("query_type") != "search":
        return {}
    catalog = _catalog_for_database(database_path)
    result = catalog.validate_plan(plan)
    if result.ok:
        return {}
    return {
        "error": {
            "code": result.error_code,
            "message": result.message,
            "details": {},
        }
    }


def authorize_plan(
    state: AgentState,
    database_path: str | Path,
    access_context: AccessContext | None,
) -> dict[str, Any]:
    plan = state.get("query_plan")
    if plan is None or state.get("query_type") != "search" or "error" in state:
        return {}
    conn = db.connect(database_path)
    try:
        result = authorize_query_plan(conn, plan, access_context)
    finally:
        conn.close()
    if result.ok:
        return {}
    return {
        "error": {
            "code": result.error_code,
            "message": result.message,
            "details": {
                "denied_fields": sorted(
                    {
                        disclosure.field_name
                        for disclosure in result.disclosures
                        if disclosure.field_name is not None
                    }
                )
            },
        }
    }


def execute_plan(
    state: AgentState,
    database_path: str | Path,
    audit_path: str | Path,
    access_context: AccessContext | None,
) -> dict[str, Any]:
    if "error" in state:
        return {}
    query_type = state.get("query_type")
    if query_type == "clarify":
        reason = state.get("clarify_reason") or "question needs a narrower retrieval scope"
        return {
            "tool_result": clarify_result(state["question"]),
            "tool_calls": [
                {
                    "tool_name": "clarify_query",
                    "reason": reason,
                    "status": "success",
                }
            ],
        }
    if query_type == "access":
        conn = db.connect(database_path)
        try:
            result = describe_my_access(
                conn,
                {"rationale": "agent_query: describe current access"},
                access_context,
            )
        finally:
            conn.close()
        return {
            "tool_result": result,
            "tool_calls": [
                {
                    "tool_name": "describe_my_access",
                    "reason": "question asks for current access scope",
                    "status": "error" if "error" in result else "success",
                }
            ],
        }

    plan = state["query_plan"]
    conn = db.connect(database_path)
    try:
        result = execute_search_plan(conn, plan, access_context=access_context)
    finally:
        conn.close()
    tool_name = f"{plan.domain}/{plan.operation}"
    return {
        "tool_result": result,
        "tool_calls": [
            {
                "tool_name": tool_name,
                "reason": "server-side retrieval plan",
                "plan": _plan_to_dict(plan),
                "status": "error" if "error" in result else "success",
            }
        ],
    }


def format_answer(state: AgentState) -> dict[str, Any]:
    if "error" in state:
        message = state["error"].get("message") or "agent query failed"
        return {"answer": message}
    result = state["tool_result"]
    if "error" in result:
        return {"error": result["error"], "answer": result["error"]["message"]}
    return {"answer": json.dumps(result, ensure_ascii=False, sort_keys=True)}


def _checkpoint_state(state: AgentState) -> dict[str, Any]:
    serializable = dict(state)
    if isinstance(serializable.get("query_plan"), QueryPlan):
        serializable["query_plan"] = _plan_to_dict(serializable["query_plan"])
    return serializable


def _plan_to_dict(plan: QueryPlan) -> dict[str, Any]:
    return asdict(plan)


def _query_plan_from_payload(payload: dict[str, Any]) -> QueryPlan:
    filters = payload.get("filters", [])
    return QueryPlan(
        domain=str(payload.get("domain", "")),
        operation=str(payload.get("operation", "")),
        filters=[
            QueryFilter(
                field=str(item.get("field", "")),
                operator=str(item.get("operator", "")),
                value=item.get("value"),
            )
            for item in filters
            if isinstance(item, dict)
        ],
        return_fields=[
            str(field)
            for field in payload.get("return_fields", [])
            if isinstance(field, str)
        ],
        limit=payload.get("limit", 20),
    )


def _record_agent_run(
    database_path: str | Path,
    thread_id: str,
    question: str,
    result: dict[str, Any],
) -> None:
    tool_calls = result.get("tool_calls") or []
    selected_tool = None
    first_call: dict[str, Any] = {}
    if tool_calls and isinstance(tool_calls[0], dict):
        first_call = tool_calls[0]
        selected_tool = first_call.get("tool_name")
    error = result.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    # A clarify is recorded as success; capture WHY in error_code so operators
    # can diagnose why a question did not retrieve data (reuses existing column).
    if error_code is None and selected_tool == "clarify_query":
        reason = first_call.get("reason")
        if isinstance(reason, str) and reason:
            error_code = f"clarify:{reason}"[:200]
    conn = db.connect(database_path)
    try:
        conn.execute(
            """
            insert into agent_runs (
              thread_id,
              question_summary,
              status,
              selected_tool,
              error_code
            )
            values (?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                question[:500],
                result.get("status", "error"),
                selected_tool,
                error_code,
            ),
        )
        conn.commit()
    finally:
        conn.close()
