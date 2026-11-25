"""Agentic Hybrid RAG 端到端流水线：支持纯 BM25、纯向量、RRF 融合与 Query 改写+重排模式。"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings
from app.rag.bm25_retriever import BM25Retriever
from app.rag.chunker import load_and_chunk_markdown_dir
from app.rag.embedder import EmbedderAdapter
from app.rag.qdrant_store import QdrantVectorStore
from app.rag.reranker import (
    QueryRewriter,
    reciprocal_rank_fusion,
    rerank_candidates,
)
from app.rag.schemas import (
    Citation,
    KnowledgeChunk,
    RagSearchResult,
    ScoredChunk,
    SearchMode,
)


class HybridRagPipeline:
    """混合 RAG 检索引擎，统一对外提供建库、多模式检索与引用溯源生成。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.embedder = EmbedderAdapter(
            backend=self.settings.embedding_backend,
            dim=self.settings.embedding_dim,
        )
        self.bm25 = BM25Retriever()
        self.qdrant = QdrantVectorStore(
            mode=self.settings.qdrant_mode,
            path=self.settings.qdrant_path,
            collection_name=self.settings.qdrant_collection,
            dim=self.settings.embedding_dim,
            embedder=self.embedder,
        )
        self.rewriter = QueryRewriter()
        self.chunks: list[KnowledgeChunk] = []
        self._indexed = False

    def index_knowledge(self, knowledge_dir: Path | None = None) -> int:
        """加载 Markdown 故障手册并构建 BM25 与 Qdrant 本地双索引。"""
        target_dir = knowledge_dir or self.settings.knowledge_dir
        self.chunks = load_and_chunk_markdown_dir(target_dir)
        self.bm25.build_index(self.chunks)
        self.qdrant.build_index(self.chunks)
        self._indexed = True
        return len(self.chunks)

    def ensure_indexed(self) -> None:
        if not self._indexed:
            self.index_knowledge()

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        mode: SearchMode = "agentic",
        service_hint: str = "",
    ) -> RagSearchResult:
        """执行指定模式的知识检索并生成标准化 Citation 溯源列表。"""
        self.ensure_indexed()

        if mode == "bm25_only":
            raw = self.bm25.search(query, top_k=top_k)
            max_s = max((s for _, s in raw), default=1.0) or 1.0
            hits = [
                ScoredChunk(
                    chunk=c,
                    bm25_score=round(s, 4),
                    rerank_score=round(s / max_s, 4),
                )
                for c, s in raw
            ]
            rewritten = [query]
        elif mode == "vector_only":
            raw = self.qdrant.search(query, top_k=top_k)
            hits = [
                ScoredChunk(
                    chunk=c,
                    vector_score=round(s, 4),
                    rerank_score=round(max(0.0, s), 4),
                )
                for c, s in raw
            ]
            rewritten = [query]
        elif mode == "hybrid_rrf":
            bm25_res = self.bm25.search(query, top_k=max(10, top_k * 3))
            vec_res = self.qdrant.search(query, top_k=max(10, top_k * 3))
            fused = reciprocal_rank_fusion([bm25_res], [vec_res])
            max_rrf = max((item.rrf_score for item in fused), default=1.0) or 1.0
            for item in fused:
                item.rerank_score = round(item.rrf_score / max_rrf, 4)
            hits = fused[:top_k]
            rewritten = [query]
        else:
            # agentic: Query 改写 + 多路 BM25 & Qdrant + RRF + 重排
            rewritten = self.rewriter.rewrite(query, service_hint=service_hint)
            bm25_lists = [self.bm25.search(q, top_k=max(12, top_k * 3)) for q in rewritten]
            vec_lists = [self.qdrant.search(q, top_k=max(12, top_k * 3)) for q in rewritten]
            fused = reciprocal_rank_fusion(bm25_lists, vec_lists)
            hits = rerank_candidates(
                query,
                fused[: max(15, top_k * 3)],
                service_hint=service_hint,
                top_k=top_k,
            )

        citations = [self._to_citation(h) for h in hits]
        return RagSearchResult(
            original_query=query,
            rewritten_queries=rewritten,
            mode=mode,
            hits=hits,
            citations=citations,
        )

    @staticmethod
    def _to_citation(hit: ScoredChunk) -> Citation:
        c = hit.chunk
        snippet = c.content.replace("\n", " ")
        if len(snippet) > 180:
            snippet = snippet[:177] + "..."
        return Citation(
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            title=c.title,
            service=c.service,
            error_code=c.error_code,
            section=c.section,
            source_path=c.source_path,
            line_range=f"L{c.line_start}-L{c.line_end}",
            score=hit.rerank_score,
            snippet=snippet,
        )
