"""FastAPI 核心路由定义：健康检查、同步排障、SSE 流式排障、人工确认与 RAG 检索。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.middleware import get_current_request_id
from app.api.schemas import (
    DiagnoseRequest,
    DiagnoseResponse,
    HealthResponse,
    HumanConfirmRequest,
    RagSearchRequest,
)

router = APIRouter()


def _format_sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check(request: Request) -> HealthResponse:
    """服务健康检查，返回当前模型模式与知识库分块数。"""
    settings = request.app.state.settings
    rag = request.app.state.rag_pipeline
    rag.ensure_indexed()
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.app_version,
        llm_provider=settings.llm_provider,
        indexed_chunks=len(rag.chunks),
        request_id=get_current_request_id(),
    )


@router.post("/api/v1/diagnose", response_model=DiagnoseResponse, tags=["agent"])
async def diagnose(req: DiagnoseRequest, request: Request) -> DiagnoseResponse:
    """执行同步智能排障诊断（含 RAG 溯源、MCP 取证、熔断保护与高危人工确认拦截）。"""
    agent_service = request.app.state.agent_service
    rid = get_current_request_id()
    result = await agent_service.run_diagnosis(
        req.query,
        request_id=rid,
        thread_id=req.thread_id,
        max_steps=req.max_steps,
        token_budget=req.token_budget,
    )
    return DiagnoseResponse(**result)


@router.post("/api/v1/diagnose/stream", tags=["agent"])
async def diagnose_stream(req: DiagnoseRequest, request: Request) -> StreamingResponse:
    """SSE 流式排障接口：实时推送节点进度、高危确认中断与最终报告流。"""
    agent_service = request.app.state.agent_service
    rid = get_current_request_id()

    async def event_generator() -> AsyncIterator[str]:
        async for evt in agent_service.stream_diagnosis(
            req.query,
            request_id=rid,
            thread_id=req.thread_id,
            max_steps=req.max_steps,
            token_budget=req.token_budget,
        ):
            yield _format_sse_event(evt["event"], evt["data"])
        yield "event: end\ndata: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-ID": rid,
        },
    )


@router.post("/api/v1/diagnose/{thread_id}/confirm", response_model=DiagnoseResponse, tags=["agent"])
async def confirm_high_risk(
    thread_id: str,
    req: HumanConfirmRequest,
    request: Request,
) -> DiagnoseResponse:
    """高危指令人工确认恢复接口。"""
    agent_service = request.app.state.agent_service
    result = await agent_service.resume_diagnosis(
        thread_id,
        approved=req.approved,
        comment=req.comment,
    )
    return DiagnoseResponse(**result)


@router.post("/api/v1/rag/search", tags=["rag"])
async def rag_search(req: RagSearchRequest, request: Request) -> dict:
    """混合 RAG 检索测试接口，支持对比 bm25_only / vector_only / hybrid_rrf / agentic。"""
    rag = request.app.state.rag_pipeline
    res = rag.search(
        req.query,
        top_k=req.top_k,
        mode=req.mode,
        service_hint=req.service_hint,
    )
    return {
        "request_id": get_current_request_id(),
        "original_query": res.original_query,
        "rewritten_queries": res.rewritten_queries,
        "mode": res.mode,
        "citations": [c.model_dump() for c in res.citations],
    }
