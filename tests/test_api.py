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


def test_source_file_provenance_and_traversal_block() -> None:
    with _create_test_client() as client:
        resp = client.get(
            "/api/v1/source/file",
            params={
                "path": "data/knowledge/01_gateway_504_timeout.md",
                "start_line": 1,
                "end_line": 10,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["language"] == "markdown"
        assert data["highlight_start"] == 1
        assert data["highlight_end"] == 10
        assert len(data["lines"]) == data["total_lines"]
        assert data["lines"][0]["line_number"] == 1

        src_resp = client.get(
            "/api/v1/source/file",
            params={"path": "gateway/application-gateway.yml", "start_line": 1, "end_line": 5},
        )
        assert src_resp.status_code == 200
        assert src_resp.json()["language"] == "yaml"

        blocked = client.get("/api/v1/source/file", params={"path": "../../.env"})
        assert blocked.status_code == 403


def test_eval_report_endpoint_40_cases() -> None:
    with _create_test_client() as client:
        resp = client.get("/api/v1/eval/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cases"] == 40
        assert len(data["case_details"]) == 40
        assert data["rag_comparison"]["agentic"]["Recall@1"] >= 0.95
        ids = {c["id"] for c in data["case_details"]}
        assert "CASE-31" in ids and "CASE-40" in ids


def test_sse_stream_rich_node_payload_and_locations() -> None:
    with _create_test_client() as client:
        with client.stream(
            "POST",
            "/api/v1/diagnose/stream",
            headers={"X-Request-ID": "trace-sse-rich-01"},
            json={"query": "刚做完滚动发版那几分钟接口偶发报错断开，怀疑旧连接被提前关掉"},
        ) as resp:
            assert resp.status_code == 200
            raw_stream = "".join(resp.iter_text())

        assert '"rag_citations"' in raw_stream
        assert '"tool_calls"' in raw_stream
        assert '"locations"' in raw_stream
        assert '"rewritten_queries"' in raw_stream
        assert '"KB-002"' in raw_stream
