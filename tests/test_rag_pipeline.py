"""RAG 混合检索与溯源单元测试。"""

from __future__ import annotations

from app.config import Settings
from app.rag.pipeline import HybridRagPipeline


def test_hybrid_rag_indexing_and_citation_provenance() -> None:
    settings = Settings(qdrant_mode="memory")
    rag = HybridRagPipeline(settings)
    chunk_count = rag.index_knowledge()

    assert chunk_count >= 50
    res = rag.search("gateway 504 ReadTimeoutException 上游超时", top_k=3, mode="agentic")
    assert len(res.citations) == 3
    top = res.citations[0]
    assert top.doc_id == "KB-001"
    assert top.service == "gateway"
    assert top.error_code == "GATEWAY-504"
    assert top.source_path.startswith("data/knowledge/")
    assert top.line_range.startswith("L")


def test_rag_query_rewrite_enhances_vague_query() -> None:
    settings = Settings(qdrant_mode="memory")
    rag = HybridRagPipeline(settings)
    rag.index_knowledge()

    res = rag.search("Kafka 消费者一直在 rebalance 导致短信积压", top_k=3, mode="agentic")
    assert len(res.rewritten_queries) >= 2
    assert any(c.doc_id == "KB-019" for c in res.citations)
