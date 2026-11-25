"""LangGraph 状态机状态定义与结构化字段说明。"""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """智能排障 Agent 全局状态对象。"""

    request_id: str
    thread_id: str
    raw_query: str
    sanitized_query: str
    compressed_query: str
    redaction_counts: dict[str, int]

    # 异常信号提取结果
    extracted_signals: dict[str, Any]

    # RAG 与工具证据
    rewritten_queries: list[str]
    retry_count: int
    max_retries: int
    rag_citations: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    tool_context: str

    # 相关性评估
    relevance_score: float
    is_relevant: bool

    # 步数与 Token 熔断保护
    step_count: int
    max_steps: int
    token_used: int
    token_budget: int
    circuit_breaker_reason: str

    # 高危指令人工确认
    requires_human_confirm: bool
    high_risk_actions: list[dict[str, str]]
    human_approved: bool | None
    human_comment: str

    # 最终输出与可观测事件
    root_cause: str
    final_report: str
    status: str
    trace_events: list[dict[str, Any]]
