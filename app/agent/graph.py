"""LangGraph 状态机构建与执行服务：支持同步执行、流式 SSE 事件输出及人工确认恢复。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agent.nodes import AgentNodes
from app.agent.state import AgentState
from app.config import Settings, get_settings
from app.gateway_client.client import GatewayClient
from app.rag.pipeline import HybridRagPipeline


class LogOpsAgentService:
    """排障 Agent 状态机对外服务封装。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        rag_pipeline: HybridRagPipeline | None = None,
        gateway_client: GatewayClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.rag = rag_pipeline or HybridRagPipeline(self.settings)
        self.rag.ensure_indexed()
        self.gateway = gateway_client or GatewayClient(self.settings)
        self.nodes = AgentNodes(self.settings, self.rag, self.gateway)
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)

        builder.add_node("extract_anomaly", self.nodes.extract_anomaly)
        builder.add_node("retrieve_and_tools", self.nodes.retrieve_and_tools)
        builder.add_node("evaluate_relevance", self.nodes.evaluate_relevance)
        builder.add_node("rewrite_and_retry", self.nodes.rewrite_and_retry)
        builder.add_node("high_risk_check", self.nodes.high_risk_check)
        builder.add_node("human_confirm", self.nodes.human_confirm)
        builder.add_node("generate_report", self.nodes.generate_report)

        builder.add_edge(START, "extract_anomaly")
        builder.add_conditional_edges(
            "extract_anomaly",
            self._route_after_extract,
            {"retrieve_and_tools": "retrieve_and_tools", "generate_report": "generate_report"},
        )
        builder.add_conditional_edges(
            "retrieve_and_tools",
            self._route_after_retrieve,
            {"evaluate_relevance": "evaluate_relevance", "generate_report": "generate_report"},
        )
        builder.add_conditional_edges(
            "evaluate_relevance",
            self._route_after_evaluate,
            {
                "rewrite_and_retry": "rewrite_and_retry",
                "high_risk_check": "high_risk_check",
                "generate_report": "generate_report",
            },
        )
        builder.add_conditional_edges(
            "rewrite_and_retry",
            self._route_after_retry,
            {"evaluate_relevance": "evaluate_relevance", "generate_report": "generate_report"},
        )
        builder.add_conditional_edges(
            "high_risk_check",
            self._route_after_risk,
            {"human_confirm": "human_confirm", "generate_report": "generate_report"},
        )
        builder.add_edge("human_confirm", "generate_report")
        builder.add_edge("generate_report", END)

        return builder.compile(checkpointer=self.checkpointer)

    @staticmethod
    def _route_after_extract(state: AgentState) -> str:
        if state.get("circuit_breaker_reason"):
            return "generate_report"
        return "retrieve_and_tools"

    @staticmethod
    def _route_after_retrieve(state: AgentState) -> str:
        if state.get("circuit_breaker_reason"):
            return "generate_report"
        return "evaluate_relevance"

    @staticmethod
    def _route_after_evaluate(state: AgentState) -> str:
        if state.get("circuit_breaker_reason"):
            return "generate_report"
        if not state.get("is_relevant", False) and state.get("retry_count", 0) < state.get("max_retries", 1):
            return "rewrite_and_retry"
        return "high_risk_check"

    @staticmethod
    def _route_after_retry(state: AgentState) -> str:
        if state.get("circuit_breaker_reason"):
            return "generate_report"
        return "evaluate_relevance"

    @staticmethod
    def _route_after_risk(state: AgentState) -> str:
        if state.get("circuit_breaker_reason"):
            return "generate_report"
        if state.get("requires_human_confirm") and state.get("human_approved") is None:
            return "human_confirm"
        return "generate_report"

    def _make_initial_state(
        self,
        query: str,
        *,
        request_id: str | None = None,
        thread_id: str | None = None,
        max_steps: int | None = None,
        token_budget: int | None = None,
        max_retries: int = 1,
    ) -> tuple[AgentState, dict[str, Any]]:
        rid = request_id or str(uuid.uuid4())
        tid = thread_id or str(uuid.uuid4())
        initial: AgentState = {
            "request_id": rid,
            "thread_id": tid,
            "raw_query": query,
            "retry_count": 0,
            "max_retries": max_retries,
            "step_count": 0,
            "max_steps": max_steps or self.settings.agent_max_steps,
            "token_used": 0,
            "token_budget": token_budget or self.settings.agent_token_budget,
            "circuit_breaker_reason": "",
            "requires_human_confirm": False,
            "high_risk_actions": [],
            "human_approved": None,
            "status": "running",
            "trace_events": [],
        }
        config = {"configurable": {"thread_id": tid}}
        return initial, config

    async def run_diagnosis(
        self,
        query: str,
        *,
        request_id: str | None = None,
        thread_id: str | None = None,
        max_steps: int | None = None,
        token_budget: int | None = None,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        """执行非流式全流程诊断；若触发高危人工确认则返回 waiting_human_confirm 状态。"""
        initial, config = self._make_initial_state(
            query,
            request_id=request_id,
            thread_id=thread_id,
            max_steps=max_steps,
            token_budget=token_budget,
            max_retries=max_retries,
        )
        result = await self.graph.ainvoke(initial, config=config)
        return self._format_snapshot_or_result(config, result)

    async def resume_diagnosis(
        self,
        thread_id: str,
        *,
        approved: bool,
        comment: str = "",
    ) -> dict[str, Any]:
        """恢复因高危指令暂停等待人工确认的状态机实例。"""
        config = {"configurable": {"thread_id": thread_id}}
        result = await self.graph.ainvoke(
            Command(resume={"approved": approved, "comment": comment}),
            config=config,
        )
        return self._format_snapshot_or_result(config, result)

    async def stream_diagnosis(
        self,
        query: str,
        *,
        request_id: str | None = None,
        thread_id: str | None = None,
        max_steps: int | None = None,
        token_budget: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式产出状态机各节点进度事件、中断事件及最终报告分片。"""
        initial, config = self._make_initial_state(
            query,
            request_id=request_id,
            thread_id=thread_id,
            max_steps=max_steps,
            token_budget=token_budget,
        )
        yield {
            "event": "start",
            "data": {
                "request_id": initial["request_id"],
                "thread_id": initial["thread_id"],
                "max_steps": initial["max_steps"],
                "token_budget": initial["token_budget"],
            },
        }

        async for chunk in self.graph.astream(initial, config=config, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                if node_name == "__interrupt__":
                    interrupt_obj = node_output[0] if isinstance(node_output, (list, tuple)) and node_output else node_output
                    payload = getattr(interrupt_obj, "value", interrupt_obj)
                    snapshot_vals = self.graph.get_state(config).values
                    enriched_payload = dict(payload) if isinstance(payload, dict) else {"value": payload}
                    enriched_payload["snapshot"] = self._extract_summary(snapshot_vals)
                    yield {"event": "human_confirm_required", "data": enriched_payload}
                    return

                out = node_output if isinstance(node_output, dict) else {}
                event_data: dict[str, Any] = {
                    "node": node_name,
                    "step_count": out.get("step_count"),
                    "token_used": out.get("token_used"),
                    "circuit_breaker_reason": out.get("circuit_breaker_reason", ""),
                }
                for key in (
                    "extracted_signals",
                    "redaction_counts",
                    "rewritten_queries",
                    "rag_citations",
                    "tool_calls",
                    "relevance_score",
                    "is_relevant",
                    "retry_count",
                    "requires_human_confirm",
                    "high_risk_actions",
                    "trace_events",
                ):
                    if key in out:
                        event_data[key] = out[key]
                yield {
                    "event": "node_update",
                    "data": event_data,
                }

        final_state = self.graph.get_state(config).values
        report = final_state.get("final_report", "")
        for i in range(0, len(report), 80):
            yield {
                "event": "token",
                "data": {"delta": report[i : i + 80], "request_id": initial["request_id"]},
            }

        yield {
            "event": "done",
            "data": self._extract_summary(final_state),
        }

    def _format_snapshot_or_result(self, config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.graph.get_state(config)
        if snapshot.tasks and any(t.interrupts for t in snapshot.tasks):
            interrupt_val = snapshot.tasks[0].interrupts[0].value
            vals = snapshot.values
            return {
                **self._extract_summary(vals),
                "status": "waiting_human_confirm",
                "interrupt": interrupt_val,
            }
        return self._extract_summary(result)

    @staticmethod
    def _extract_summary(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": state.get("request_id", ""),
            "thread_id": state.get("thread_id", ""),
            "status": state.get("status", "completed"),
            "root_cause": state.get("root_cause", ""),
            "final_report": state.get("final_report", ""),
            "rag_citations": state.get("rag_citations", []),
            "tool_calls": state.get("tool_calls", []),
            "rewritten_queries": state.get("rewritten_queries", []),
            "relevance_score": state.get("relevance_score", 0.0),
            "retry_count": state.get("retry_count", 0),
            "step_count": state.get("step_count", 0),
            "token_used": state.get("token_used", 0),
            "circuit_breaker_reason": state.get("circuit_breaker_reason", ""),
            "requires_human_confirm": state.get("requires_human_confirm", False),
            "high_risk_actions": state.get("high_risk_actions", []),
            "human_approved": state.get("human_approved"),
            "redaction_counts": state.get("redaction_counts", {}),
            "trace_events": state.get("trace_events", []),
        }
