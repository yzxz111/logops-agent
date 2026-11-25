"""Request-ID 上下文透传中间件。"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="")


def get_current_request_id() -> str:
    """获取当前协程上下文中的 Request-ID。"""
    return request_id_ctx.get()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """读取或生成 X-Request-ID，写入上下文并透传到响应头。"""

    HEADER_NAME = "X-Request-ID"

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(self.HEADER_NAME) or request.headers.get("x-request-id")
        rid = incoming.strip() if incoming and incoming.strip() else str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        request.state.request_id = rid
        try:
            response = await call_next(request)
            response.headers[self.HEADER_NAME] = rid
            return response
        finally:
            request_id_ctx.reset(token)
