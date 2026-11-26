"""FastAPI 核心路由定义：健康检查、同步排障、SSE 流式排障、人工确认与 RAG 检索。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.middleware import get_current_request_id
from app.api.schemas import (
    DiagnoseRequest,
    DiagnoseResponse,
    HealthResponse,
    HumanConfirmRequest,
    RagSearchRequest,
)
from app.config import PROJECT_ROOT
from app.context.sanitizer import sanitize_text

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


def _resolve_safe_data_file(rel_path: str) -> tuple[Path, str]:
    """安全解析 data/ 目录下的只读文件，阻断路径穿越与越权访问。"""
    cleaned = rel_path.strip().replace("\\", "/").lstrip("/")
    if not cleaned or ".." in Path(cleaned).parts:
        raise HTTPException(status_code=403, detail="越权路径访问被拦截")

    data_root = (PROJECT_ROOT / "data").resolve()
    candidates: list[Path] = []
    if cleaned.startswith("data/"):
        candidates.append((PROJECT_ROOT / cleaned).resolve())
    else:
        candidates.append((data_root / "mock_source" / cleaned).resolve())
        candidates.append((data_root / "mock_logs" / cleaned).resolve())
        candidates.append((data_root / "knowledge" / cleaned).resolve())

    for target in candidates:
        if target != data_root and data_root not in target.parents:
            raise HTTPException(status_code=403, detail="越权路径访问被拦截")
        if target.is_file():
            return target, target.relative_to(PROJECT_ROOT).as_posix()

    raise HTTPException(status_code=404, detail=f"未找到目标文件: {rel_path}")


def _infer_language(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix == ".java":
        return "java"
    if suffix in {".yml", ".yaml"}:
        return "yaml"
    if suffix == ".log":
        return "log"
    return "text"


@router.get("/api/v1/source/file", tags=["provenance"])
async def read_source_file(
    path: str = Query(..., min_length=1, description="data/ 下的相对路径"),
    start_line: int = Query(default=1, ge=1),
    end_line: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """只读读取知识手册、模拟日志或源码片段，供前端 Citation 溯源抽屉高亮展示。"""
    target, rel_posix = _resolve_safe_data_file(path)
    raw_lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    sanitized_lines = [sanitize_text(line).sanitized_text for line in raw_lines]
    total_lines = len(sanitized_lines)
    safe_start = min(start_line, max(1, total_lines))
    safe_end = min(end_line or total_lines, total_lines)
    if safe_end < safe_start:
        safe_end = safe_start

    return {
        "request_id": get_current_request_id(),
        "path": rel_posix,
        "language": _infer_language(target),
        "total_lines": total_lines,
        "highlight_start": safe_start,
        "highlight_end": safe_end,
        "lines": [
            {"line_number": idx + 1, "content": content}
            for idx, content in enumerate(sanitized_lines)
        ],
    }


def _load_eval_payload() -> dict[str, Any]:
    report_path = PROJECT_ROOT / "eval" / "eval_report.json"
    dataset_path = PROJECT_ROOT / "eval" / "dataset.json"
    if not report_path.exists() or not dataset_path.exists():
        raise HTTPException(status_code=404, detail="评测报告或数据集尚未生成")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    case_meta = {item["id"]: item for item in dataset}

    enriched_details: list[dict[str, Any]] = []
    for detail in report.get("case_details", []):
        meta = case_meta.get(detail["id"], {})
        enriched_details.append({
            **detail,
            "query": meta.get("query", ""),
            "difficulty": meta.get("difficulty", "medium"),
            "expected_doc_ids": meta.get("expected_doc_ids", []),
            "expected_service": meta.get("expected_service", ""),
            "has_high_risk_action": bool(meta.get("has_high_risk_action", False)),
        })

    return {
        "request_id": get_current_request_id(),
        "total_cases": report.get("total_cases", len(enriched_details)),
        "indexed_chunks": report.get("indexed_chunks", 0),
        "rag_comparison": report.get("rag_comparison", {}),
        "agent_metrics": report.get("agent_metrics", {}),
        "case_details": enriched_details,
    }


@router.get("/api/v1/eval/report", tags=["eval"])
async def get_eval_report() -> dict[str, Any]:
    """读取最新评测对比数据与样本明细，供前端评测看板展示。"""
    return _load_eval_payload()


@router.post("/api/v1/eval/run", tags=["eval"])
async def trigger_eval_run() -> dict[str, Any]:
    """现场重跑评测脚本并返回最新评测看板数据。"""
    from eval.run_eval import run_evaluation

    await run_evaluation()
    return _load_eval_payload()
