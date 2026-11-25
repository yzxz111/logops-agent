"""FastAPI API 服务模块：SSE 流式接口、Request-ID 透传与人工确认恢复。"""

from app.api.main import app, create_app

__all__ = ["app", "create_app"]
