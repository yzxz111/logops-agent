"""BM25 稀疏检索器，针对错误码、异常类名、服务名与中文运维术语优化。"""

from __future__ import annotations

from rank_bm25 import BM25Okapi

from app.rag.embedder import tokenize_mixed
from app.rag.schemas import KnowledgeChunk


class BM25Retriever:
    """基于 rank_bm25 的内存稀疏检索器。"""

    def __init__(self) -> None:
        self._chunks: list[KnowledgeChunk] = []
        self._bm25: BM25Okapi | None = None

    def build_index(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks = chunks
        if not chunks:
            self._bm25 = None
            return
        corpus = [
            tokenize_mixed(
                f"{c.error_code} {c.error_code} {c.service} {c.title} {' '.join(c.keywords)} {c.content}",
                expand_synonyms=False,
            )
            for c in chunks
        ]
        self._bm25 = BM25Okapi(corpus)

    def search(self, query: str, top_k: int = 10) -> list[tuple[KnowledgeChunk, float]]:
        if not self._bm25 or not self._chunks:
            return []
        q_tokens = tokenize_mixed(query, expand_synonyms=False)
        if not q_tokens:
            return []
        scores = self._bm25.get_scores(q_tokens)
        ranked_indices = sorted(
            range(len(self._chunks)),
            key=lambda i: float(scores[i]),
            reverse=True,
        )[:top_k]
        return [
            (self._chunks[i], float(scores[i]))
            for i in ranked_indices
            if float(scores[i]) > 0.0
        ]
