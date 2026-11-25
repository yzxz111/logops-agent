"""FastAPI 接口请求与响应模型。"""

from typing import Any

from pydantic import BaseModel, Field

from app.rag.schemas import SearchMode


class DiagnoseRequest(BaseModel):
    """排障诊断请求体。"""

    query: str = Field(..., min_length=2, description="用户故障描述或异常堆栈日志")
    thread_id: str | None = Field(default=None, description="可选会话/排障线程 ID")
    max_steps: int | None = Field(default=None, ge=2, le=20, description="覆盖最大步数限制")
    token_budget: int | None = Field(default=None, ge=100, le=50000, description="覆盖 Token 预算上限")


class HumanConfirmRequest(BaseModel):
    """高危指令人工确认请求体。"""

    approved: bool = Field(..., description="是否同意高危操作；false 则降级为只读建议")
    comment: str = Field(default="", max_length=300, description="审批意见")


class RagSearchRequest(BaseModel):
    """混合 RAG 检索调试请求体。"""

    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: SearchMode = Field(default="agentic")
    service_hint: str = Field(default="")


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str
    app_name: str
    version: str
    llm_provider: str
    indexed_chunks: int
    request_id: str


class DiagnoseResponse(BaseModel):
    """非流式排障诊断响应。"""

    request_id: str
    thread_id: str
    status: str
    root_cause: str
    final_report: str
    rag_citations: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    rewritten_queries: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0
    retry_count: int = 0
    step_count: int = 0
    token_used: int = 0
    circuit_breaker_reason: str = ""
    requires_human_confirm: bool = False
    high_risk_actions: list[dict[str, str]] = Field(default_factory=list)
    human_approved: bool | None = None
    redaction_counts: dict[str, int] = Field(default_factory=dict)
    interrupt: dict[str, Any] | None = None
