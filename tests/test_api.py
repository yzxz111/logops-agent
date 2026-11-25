"""FastAPI 接口与 SSE 流式端到端测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings


def _create_test_client() -> TestClient:
    app = create_app(Settings(llm_provider="mock", qdrant_mode="memory"))
    return TestClient(app)


def test_health_and_request_id_passthrough() -> None:
    with _create_test_client() as client:
        resp = client.get("/health", headers={"X-Request-ID": "trace-health-888"})
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"] == "trace-health-888"
        body = resp.json()
        assert body["status"] == "ok"
        assert body["indexed_chunks"] >= 50
        assert body["request_id"] == "trace-health-888"


def test_diagnose_sse_stream_endpoint() -> None:
    with _create_test_client() as client:
        with client.stream(
            "POST",
            "/api/v1/diagnose/stream",
            headers={"X-Request-ID": "trace-sse-101"},
            json={"query": "gateway 返回 502 PrematureCloseException"},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["X-Request-ID"] == "trace-sse-101"
            raw_stream = "".join(resp.iter_text())

        assert "event: start" in raw_stream
        assert "event: node_update" in raw_stream
        assert "event: token" in raw_stream
        assert "event: done" in raw_stream
        assert "data: [DONE]" in raw_stream


def test_diagnose_high_risk_and_confirm_api() -> None:
    with _create_test_client() as client:
        resp = client.post(
            "/api/v1/diagnose",
            json={
                "query": "payment pod 卡死，准备执行 kubectl delete pod --force",
                "thread_id": "api-confirm-01",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "waiting_human_confirm"

        confirm_resp = client.post(
            "/api/v1/diagnose/api-confirm-01/confirm",
            json={"approved": True, "comment": "已完成摘流，批准重启"},
        )
        assert confirm_resp.status_code == 200
        c_data = confirm_resp.json()
        assert c_data["status"] == "completed"
        assert c_data["human_approved"] is True
        assert "已获人工确认批准执行" in c_data["final_report"]
