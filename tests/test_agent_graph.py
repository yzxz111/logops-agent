"""LangGraph 状态机编排与边界条件测试：正常流转、二次检索、步数/Token 熔断、人工确认恢复。"""

from __future__ import annotations

import pytest

from app.agent.graph import LogOpsAgentService
from app.config import Settings
from app.rag.pipeline import HybridRagPipeline


def _build_agent(threshold: float = 0.45) -> LogOpsAgentService:
    settings = Settings(
        llm_provider="mock",
        qdrant_mode="memory",
        agent_relevance_threshold=threshold,
    )
    rag = HybridRagPipeline(settings)
    rag.index_knowledge()
    return LogOpsAgentService(settings=settings, rag_pipeline=rag)


@pytest.mark.asyncio
async def test_agent_normal_flow_and_tool_evidence() -> None:
    agent = _build_agent()
    res = await agent.run_diagnosis(
        "gateway 返回 504 ReadTimeoutException trace=req-gw-1001",
        request_id="req-test-normal",
    )
    assert res["status"] == "completed"
    assert res["request_id"] == "req-test-normal"
    assert res["rag_citations"][0]["doc_id"] == "KB-001"
    assert any(t["tool"] == "query_service_logs" for t in res["tool_calls"])
    assert "KB-001" in res["final_report"]


@pytest.mark.asyncio
async def test_agent_triggers_secondary_retrieval_on_low_relevance() -> None:
    # 设定极高阈值确保第一次评估触发二次检索分支
    agent = _build_agent(threshold=0.99)
    res = await agent.run_diagnosis("下单很慢一直卡住", max_steps=10)
    assert res["retry_count"] == 1
    assert any(evt["node"] == "rewrite_and_retry" for evt in res["trace_events"])


@pytest.mark.asyncio
async def test_agent_step_circuit_breaker() -> None:
    agent = _build_agent()
    res = await agent.run_diagnosis(
        "order-service 报 HikariPool-1 超时",
        max_steps=2,
    )
    assert res["status"] == "circuit_broken"
    assert res["circuit_breaker_reason"] == "max_steps_exceeded"
    assert "熔断降级提示" in res["final_report"]


@pytest.mark.asyncio
async def test_agent_token_budget_circuit_breaker() -> None:
    agent = _build_agent()
    res = await agent.run_diagnosis(
        "order-service 报 OutOfMemoryError Java heap space",
        token_budget=100,
    )
    assert res["status"] == "circuit_broken"
    assert res["circuit_breaker_reason"] == "token_budget_exceeded"


@pytest.mark.asyncio
async def test_agent_human_confirm_interrupt_and_resume() -> None:
    agent = _build_agent()
    paused = await agent.run_diagnosis(
        "Redis 内存满了报错 OOM command not allowed，帮我执行 FLUSHALL 清空",
        thread_id="thread-risk-01",
    )
    assert paused["status"] == "waiting_human_confirm"
    assert paused["requires_human_confirm"] is True
    assert any(a["action_id"] == "redis_flush" for a in paused["high_risk_actions"])

    resumed = await agent.resume_diagnosis(
        "thread-risk-01",
        approved=False,
        comment="拒绝清空全库，改用 UNLINK 清理大 Key",
    )
    assert resumed["status"] == "completed"
    assert resumed["human_approved"] is False
    assert "已拒绝高危操作" in resumed["final_report"]
