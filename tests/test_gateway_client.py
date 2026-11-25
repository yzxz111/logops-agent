"""Gateway 客户端单元测试：429 退避重试、SSE 解析、Request-ID 透传。"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.gateway_client.client import GatewayClient, RateLimitExhaustedError


@pytest.mark.asyncio
async def test_gateway_429_backoff_and_request_id_passthrough() -> None:
    attempts = 0
    seen_request_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        seen_request_ids.append(request.headers.get("X-Request-ID", ""))
        if attempts < 3:
            return httpx.Response(
                429,
                headers={"Retry-After": "0.01", "X-Request-ID": request.headers["X-Request-ID"]},
                json={"error": "rate_limited"},
            )
        return httpx.Response(
            200,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
            json={
                "id": "chatcmpl-123",
                "model": "gpt-4o-mini",
                "choices": [{"message": {"role": "assistant", "content": "504 root cause ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        settings = Settings(
            llm_provider="gateway",
            gateway_base_url="http://mock-gateway/v1",
            gateway_api_key="sk-test",
            gateway_max_retries=3,
            gateway_backoff_base=0.01,
        )
        client = GatewayClient(settings=settings, http_client=http_client)
        resp = await client.chat_completions(
            [{"role": "user", "content": "check 504"}],
            request_id="rid-custom-999",
        )

    assert attempts == 3
    assert seen_request_ids == ["rid-custom-999", "rid-custom-999", "rid-custom-999"]
    assert resp.content == "504 root cause ok"
    assert resp.request_id == "rid-custom-999"
    assert resp.usage.total_tokens == 30


@pytest.mark.asyncio
async def test_gateway_429_exhausted_raises_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0.01"}, json={"error": "too many requests"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        settings = Settings(
            llm_provider="gateway",
            gateway_base_url="http://mock-gateway/v1",
            gateway_max_retries=1,
            gateway_backoff_base=0.01,
        )
        client = GatewayClient(settings=settings, http_client=http_client)
        with pytest.raises(RateLimitExhaustedError):
            await client.chat_completions([{"role": "user", "content": "hi"}], request_id="rid-429")


@pytest.mark.asyncio
async def test_gateway_sse_stream_parsing() -> None:
    sse_payload = (
        ": keepalive\n\n"
        'data: {"id":"c1","model":"gpt-4o-mini","choices":[{"delta":{"content":"根因"},"finish_reason":null}]}\n\n'
        'data: {"id":"c1","model":"gpt-4o-mini","choices":[{"delta":{"content":"定位完成"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream", "X-Request-ID": request.headers["X-Request-ID"]},
            content=sse_payload,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        settings = Settings(llm_provider="gateway", gateway_base_url="http://mock-gateway/v1")
        client = GatewayClient(settings=settings, http_client=http_client)
        chunks = [
            chunk
            async for chunk in client.stream_chat_completions(
                [{"role": "user", "content": "stream"}],
                request_id="rid-sse-01",
            )
        ]

    text = "".join(c.delta_content for c in chunks)
    assert text == "根因定位完成"
    assert chunks[-1].is_done is True
    assert chunks[0].request_id == "rid-sse-01"
