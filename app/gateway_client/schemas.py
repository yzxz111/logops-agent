"""Gateway 客户端数据模型定义（OpenAI 兼容格式）。"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """标准对话消息体。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None


class TokenUsage(BaseModel):
    """Token 消耗统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """非流式对话补全响应。"""

    id: str = ""
    model: str = ""
    content: str = ""
    finish_reason: str | None = "stop"
    usage: TokenUsage = Field(default_factory=TokenUsage)
    request_id: str | None = None
    provider: str = "gateway"
    raw: dict[str, Any] = Field(default_factory=dict)


class StreamChunk(BaseModel):
    """SSE 流式解析出的单个增量块。"""

    id: str = ""
    model: str = ""
    delta_content: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    is_done: bool = False
    request_id: str | None = None
