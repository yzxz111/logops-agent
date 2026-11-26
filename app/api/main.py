"""FastAPI 应用装配入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent.graph import LogOpsAgentService
from app.api.middleware import RequestIdMiddleware
from app.api.routes import router
from app.config import Settings, get_settings
from app.gateway_client.client import GatewayClient
from app.rag.pipeline import HybridRagPipeline


def create_app(settings: Settings | None = None) -> FastAPI:
    """构造 FastAPI 实例并初始化 RAG 索引、网关客户端与 LangGraph 服务。"""
    cfg = settings or get_settings()
    rag_pipeline = HybridRagPipeline(cfg)
    gateway_client = GatewayClient(cfg)
    agent_service = LogOpsAgentService(
        settings=cfg,
        rag_pipeline=rag_pipeline,
        gateway_client=gateway_client,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        rag_pipeline.ensure_indexed()
        yield

    application = FastAPI(
        title=cfg.app_name,
        version=cfg.app_version,
        description="智能运维排障 Agent 平台 (FastAPI SSE + LangGraph + Hybrid RAG + ReadOnly MCP)",
        lifespan=lifespan,
    )
    application.state.settings = cfg
    application.state.rag_pipeline = rag_pipeline
    application.state.gateway_client = gateway_client
    application.state.agent_service = agent_service

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    application.add_middleware(RequestIdMiddleware)
    application.include_router(router)

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.is_dir():
        application.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return application


app = create_app()
