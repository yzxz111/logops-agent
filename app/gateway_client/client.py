"""异步 OpenAI 兼容网关客户端，支持 Request-ID 透传、429 指数退避与 SSE 流式解析。"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.gateway_client.schemas import (
    ChatCompletionResponse,
    ChatMessage,
    StreamChunk,
    TokenUsage,
)


class GatewayError(RuntimeError):
    """模型网关调用基础异常。"""

    def __init__(self, message: str, status_code: int | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class RateLimitExhaustedError(GatewayError):
    """429 限流重试耗尽异常。"""


def estimate_tokens(text: str) -> int:
    """轻量级中英文 Token 估算器（无需外部 tokenizer 下载）。"""
    if not text:
        return 0
    cjk_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other_chars = len(text) - cjk_chars
    return max(1, int(cjk_chars * 1.3 + other_chars / 3.8))


def parse_sse_data_line(line: str) -> dict[str, Any] | LiteralDone | None:
    """解析单行 SSE payload，返回 JSON 字典、DONE 哨兵或 None（非 data 行/空行）。"""
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return None
    if not stripped.startswith("data:"):
        return None
    payload = stripped[len("data:") :].strip()
    if not payload:
        return None
    if payload == "[DONE]":
        return _DONE_SENTINEL
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


class LiteralDone:
    """SSE [DONE] 结束哨兵标记。"""


_DONE_SENTINEL = LiteralDone()


class GatewayClient:
    """对接 Java「AI 模型接入与网关平台」及公共 OpenAI 兼容 API 的客户端。"""

    RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._external_client = http_client

    def _build_headers(self, request_id: str | None = None) -> tuple[dict[str, str], str]:
        rid = request_id or str(uuid.uuid4())
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": rid,
        }
        api_key = self.settings.active_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers, rid

    def _chat_endpoint(self) -> str:
        base = self.settings.active_base_url()
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _embeddings_endpoint(self) -> str:
        base = self.settings.active_base_url()
        if base.endswith("/embeddings"):
            return base
        return f"{base}/embeddings"

    def _compute_backoff_delay(self, attempt: int, retry_after: str | None = None) -> float:
        """计算 429/5xx 退避时间：优先使用 Retry-After，否则指数退避加抖动。"""
        if retry_after:
            try:
                parsed = float(retry_after)
                if parsed >= 0:
                    return min(parsed, self.settings.gateway_backoff_max)
            except ValueError:
                pass
        exp = self.settings.gateway_backoff_base * (2**attempt)
        jitter = random.uniform(0.0, 0.25 * self.settings.gateway_backoff_base)
        return min(exp + jitter, self.settings.gateway_backoff_max)

    async def _get_client(self) -> tuple[httpx.AsyncClient, bool]:
        if self._external_client is not None:
            return self._external_client, False
        client = httpx.AsyncClient(timeout=self.settings.gateway_timeout_seconds)
        return client, True

    async def chat_completions(
        self,
        messages: list[ChatMessage] | list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        request_id: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> ChatCompletionResponse:
        """发送非流式对话补全请求，内置 429 指数退避与 Request-ID 透传。"""
        normalized_msgs = [
            m.model_dump(exclude_none=True) if isinstance(m, ChatMessage) else m for m in messages
        ]
        rid = request_id or str(uuid.uuid4())
        target_model = model or self.settings.active_model()

        if self.settings.llm_provider == "mock":
            return self._mock_completion(normalized_msgs, target_model, rid)

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": normalized_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if extra_body:
            payload.update(extra_body)

        headers, rid = self._build_headers(rid)
        url = self._chat_endpoint()
        client, should_close = await self._get_client()

        try:
            last_error: Exception | None = None
            for attempt in range(self.settings.gateway_max_retries + 1):
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                except httpx.RequestError as exc:
                    last_error = exc
                    if attempt < self.settings.gateway_max_retries:
                        await asyncio.sleep(self._compute_backoff_delay(attempt))
                        continue
                    if self.settings.allow_mock_fallback:
                        return self._mock_completion(normalized_msgs, target_model, rid)
                    raise GatewayError(
                        f"网关连接失败: {exc}", request_id=rid
                    ) from exc

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices") or []
                    first = choices[0] if choices else {}
                    msg = first.get("message") or {}
                    usage_raw = data.get("usage") or {}
                    content = msg.get("content", "")
                    prompt_tokens = usage_raw.get(
                        "prompt_tokens",
                        sum(estimate_tokens(m.get("content", "")) for m in normalized_msgs),
                    )
                    completion_tokens = usage_raw.get(
                        "completion_tokens", estimate_tokens(content)
                    )
                    total_tokens = usage_raw.get(
                        "total_tokens", prompt_tokens + completion_tokens
                    )
                    return ChatCompletionResponse(
                        id=data.get("id", ""),
                        model=data.get("model", target_model),
                        content=content,
                        finish_reason=first.get("finish_reason"),
                        usage=TokenUsage(
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=total_tokens,
                        ),
                        request_id=resp.headers.get("X-Request-ID", rid),
                        provider=self.settings.llm_provider,
                        raw=data,
                    )

                if resp.status_code in self.RETRYABLE_STATUS_CODES:
                    if attempt < self.settings.gateway_max_retries:
                        delay = self._compute_backoff_delay(
                            attempt, resp.headers.get("Retry-After")
                        )
                        await asyncio.sleep(delay)
                        continue
                    if resp.status_code == 429:
                        raise RateLimitExhaustedError(
                            f"网关限流 (HTTP 429)，已重试 {self.settings.gateway_max_retries} 次仍失败",
                            status_code=429,
                            request_id=rid,
                        )
                    raise GatewayError(
                        f"网关服务不可用 (HTTP {resp.status_code}): {resp.text[:200]}",
                        status_code=resp.status_code,
                        request_id=rid,
                    )

                raise GatewayError(
                    f"网关返回错误 (HTTP {resp.status_code}): {resp.text[:300]}",
                    status_code=resp.status_code,
                    request_id=rid,
                )

            if last_error and self.settings.allow_mock_fallback:
                return self._mock_completion(normalized_msgs, target_model, rid)
            raise GatewayError("未知网关请求失败", request_id=rid)
        finally:
            if should_close:
                await client.aclose()

    async def stream_chat_completions(
        self,
        messages: list[ChatMessage] | list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        request_id: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """流式对话补全，支持 429 重试与 OpenAI SSE 格式逐块解析。"""
        normalized_msgs = [
            m.model_dump(exclude_none=True) if isinstance(m, ChatMessage) else m for m in messages
        ]
        rid = request_id or str(uuid.uuid4())
        target_model = model or self.settings.active_model()

        if self.settings.llm_provider == "mock":
            mock_resp = self._mock_completion(normalized_msgs, target_model, rid)
            chunk_size = 24
            text = mock_resp.content
            for idx in range(0, max(1, len(text)), chunk_size):
                piece = text[idx : idx + chunk_size]
                yield StreamChunk(
                    id=mock_resp.id,
                    model=target_model,
                    delta_content=piece,
                    request_id=rid,
                )
                await asyncio.sleep(0.005)
            yield StreamChunk(
                id=mock_resp.id,
                model=target_model,
                finish_reason="stop",
                usage=mock_resp.usage,
                is_done=True,
                request_id=rid,
            )
            return

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": normalized_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        headers, rid = self._build_headers(rid)
        url = self._chat_endpoint()
        client, should_close = await self._get_client()

        try:
            for attempt in range(self.settings.gateway_max_retries + 1):
                try:
                    async with client.stream("POST", url, json=payload, headers=headers) as resp:
                        if resp.status_code in self.RETRYABLE_STATUS_CODES:
                            retry_after = resp.headers.get("Retry-After")
                            await resp.aread()
                            if attempt < self.settings.gateway_max_retries:
                                await asyncio.sleep(self._compute_backoff_delay(attempt, retry_after))
                                continue
                            if resp.status_code == 429:
                                raise RateLimitExhaustedError(
                                    "流式请求触发网关 429 限流且重试耗尽",
                                    status_code=429,
                                    request_id=rid,
                                )
                            raise GatewayError(
                                f"流式请求失败 (HTTP {resp.status_code})",
                                status_code=resp.status_code,
                                request_id=rid,
                            )

                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", errors="ignore")
                            raise GatewayError(
                                f"流式请求返回 HTTP {resp.status_code}: {body[:200]}",
                                status_code=resp.status_code,
                                request_id=rid,
                            )

                        resp_rid = resp.headers.get("X-Request-ID", rid)
                        async for line in resp.aiter_lines():
                            parsed = parse_sse_data_line(line)
                            if parsed is None:
                                continue
                            if parsed is _DONE_SENTINEL:
                                yield StreamChunk(
                                    model=target_model,
                                    is_done=True,
                                    finish_reason="stop",
                                    request_id=resp_rid,
                                )
                                return

                            choices = parsed.get("choices") or []
                            first = choices[0] if choices else {}
                            delta = first.get("delta") or {}
                            usage_raw = parsed.get("usage")
                            usage = TokenUsage(**usage_raw) if isinstance(usage_raw, dict) else None
                            yield StreamChunk(
                                id=parsed.get("id", ""),
                                model=parsed.get("model", target_model),
                                delta_content=delta.get("content") or "",
                                finish_reason=first.get("finish_reason"),
                                usage=usage,
                                is_done=False,
                                request_id=resp_rid,
                            )
                        return
                except httpx.RequestError as exc:
                    if attempt < self.settings.gateway_max_retries:
                        await asyncio.sleep(self._compute_backoff_delay(attempt))
                        continue
                    if self.settings.allow_mock_fallback:
                        async for chunk in self._fallback_stream(normalized_msgs, target_model, rid):
                            yield chunk
                        return
                    raise GatewayError(f"流式连接失败: {exc}", request_id=rid) from exc
        finally:
            if should_close:
                await client.aclose()

    async def create_embeddings(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        request_id: str | None = None,
    ) -> list[list[float]]:
        """调用网关 OpenAI 兼容 /embeddings 接口生成稠密向量。"""
        headers, rid = self._build_headers(request_id)
        payload = {
            "model": model or self.settings.gateway_embedding_model,
            "input": texts,
        }
        client, should_close = await self._get_client()
        try:
            resp = await client.post(self._embeddings_endpoint(), json=payload, headers=headers)
            if resp.status_code != 200:
                raise GatewayError(
                    f"Embeddings 调用失败 (HTTP {resp.status_code}): {resp.text[:200]}",
                    status_code=resp.status_code,
                    request_id=rid,
                )
            data = resp.json().get("data") or []
            data_sorted = sorted(data, key=lambda item: item.get("index", 0))
            return [item["embedding"] for item in data_sorted]
        finally:
            if should_close:
                await client.aclose()

    async def _fallback_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        request_id: str,
    ) -> AsyncIterator[StreamChunk]:
        mock_resp = self._mock_completion(messages, model, request_id)
        yield StreamChunk(
            id=mock_resp.id,
            model=model,
            delta_content=mock_resp.content,
            finish_reason="stop",
            usage=mock_resp.usage,
            is_done=True,
            request_id=request_id,
        )

    def _mock_completion(
        self,
        messages: list[dict[str, str]],
        model: str,
        request_id: str,
    ) -> ChatCompletionResponse:
        """离线 Mock 模式下的确定性摘要与根因响应，便于无外网/无 Key 本地闭环。"""
        user_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        prompt_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        summary = (
            "### 智能排障分析（离线网关模拟响应）\n"
            f"- **Request-ID**: `{request_id}`\n"
            f"- **分析摘要**: 已基于检索到的故障手册与服务日志切片完成根因定位，详情见各证据节点。\n"
            f"- **输入长度**: {len(user_text)} 字符"
        )
        completion_tokens = estimate_tokens(summary)
        return ChatCompletionResponse(
            id=f"chatcmpl-mock-{request_id[:8]}",
            model=model,
            content=summary,
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            request_id=request_id,
            provider="mock",
        )
