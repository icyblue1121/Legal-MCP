from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, TypedDict

from legal_mcp import db
from legal_mcp.agent_observability import build_trace_metadata, langfuse_callbacks
from legal_mcp.agent_router import clarify_result, route_question, validate_agent_decision
from legal_mcp.audit import DEFAULT_AUDIT_PATH
from legal_mcp.policy import AccessContext


class AgentState(TypedDict, total=False):
    question: str
    decision: dict[str, Any]
    tool_result: dict[str, Any]
    answer: str
    error: dict[str, Any]
    tool_calls: list[dict[str, Any]]


def run_agent_query(
    *,
    question: str,
    database_path: str | Path,
    checkpoint_path: str | Path | None = None,
    audit_path: str | Path = DEFAULT_AUDIT_PATH,
    access_context: AccessContext | None = None,
    thread_id: str | None = None,
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
    )
    result: dict[str, Any] = {
        "answer": state.get("answer", ""),
        "thread_id": actual_thread_id,
        "tool_calls": state.get("tool_calls", []),
        "status": "error" if state.get("error") else "success",
    }
    if state.get("error"):
        result["error"] = state["error"]
    _record_agent_run(database_path, actual_thread_id, question, result)
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
        )
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        callbacks = langfuse_callbacks()
        if callbacks:
            config["callbacks"] = callbacks
            config["metadata"] = build_trace_metadata(
                thread_id=thread_id,
                tool_name=None,
                status="started",
            )
        return graph.invoke({"question": question}, config)
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
) -> Any:
    workflow = state_graph_cls(AgentState)
    workflow.add_node(
        "route",
        lambda state: _route_node(state),
    )
    workflow.add_node(
        "execute_tool",
        lambda state: _tool_node(state, database_path, audit_path, access_context),
    )
    workflow.add_node("answer", _answer_node)
    workflow.add_edge(start, "route")
    workflow.add_edge("route", "execute_tool")
    workflow.add_edge("execute_tool", "answer")
    workflow.add_edge("answer", end)
    return workflow.compile(checkpointer=checkpointer)


def _run_linear_graph(
    *,
    question: str,
    database_path: str | Path,
    audit_path: str | Path,
    access_context: AccessContext | None,
    checkpoint_path: Path,
    thread_id: str,
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
        for node_name, update in (
            ("route", _route_node(state)),
            ("execute_tool", {}),
            ("answer", {}),
        ):
            if node_name == "execute_tool":
                update = _tool_node(state, database_path, audit_path, access_context)
            elif node_name == "answer":
                update = _answer_node(state)
            state.update(update)
            checkpoint_conn.execute(
                """
                insert into agent_checkpoints (thread_id, node, state_json)
                values (?, ?, ?)
                """,
                (thread_id, node_name, json.dumps(state, ensure_ascii=False, sort_keys=True)),
            )
        checkpoint_conn.commit()
        return state
    finally:
        checkpoint_conn.close()


def _route_node(state: AgentState) -> dict[str, Any]:
    decision = route_question(state["question"])
    validation = validate_agent_decision(decision)
    if "error" in validation and decision.tool_name != "clarify_query":
        return {"error": validation["error"]}
    return {
        "decision": {
            "tool_name": decision.tool_name,
            "arguments": decision.arguments,
            "reason": decision.reason,
        }
    }


def _tool_node(
    state: AgentState,
    database_path: str | Path,
    audit_path: str | Path,
    access_context: AccessContext | None,
) -> dict[str, Any]:
    if "error" in state:
        return {}
    decision = state["decision"]
    if decision["tool_name"] == "clarify_query":
        return {
            "tool_result": clarify_result(state["question"]),
            "tool_calls": [
                {
                    "tool_name": "clarify_query",
                    "reason": decision["reason"],
                    "status": "success",
                }
            ],
        }

    from legal_mcp.tools import call_tool

    result = call_tool(
        decision["tool_name"],
        decision["arguments"],
        database_path=database_path,
        audit_path=audit_path,
        access_context=access_context,
    )
    return {
        "tool_result": result,
        "tool_calls": [
            {
                "tool_name": decision["tool_name"],
                "reason": decision["reason"],
                "status": "error" if "error" in result else "success",
            }
        ],
    }


def _answer_node(state: AgentState) -> dict[str, Any]:
    if "error" in state:
        return {"answer": state["error"]["message"]}
    result = state["tool_result"]
    if "error" in result:
        return {"error": result["error"], "answer": result["error"]["message"]}
    return {"answer": json.dumps(result, ensure_ascii=False, sort_keys=True)}


def _record_agent_run(
    database_path: str | Path,
    thread_id: str,
    question: str,
    result: dict[str, Any],
) -> None:
    tool_calls = result.get("tool_calls") or []
    selected_tool = None
    if tool_calls and isinstance(tool_calls[0], dict):
        selected_tool = tool_calls[0].get("tool_name")
    error = result.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
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
