"""Qdrant 本地模式向量存储与检索器（支持 memory 与磁盘持久化）。"""

from __future__ import annotations

import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.rag.embedder import EmbedderAdapter
from app.rag.schemas import KnowledgeChunk


class QdrantVectorStore:
    """Qdrant 本地模式向量索引封装。"""

    def __init__(
        self,
        *,
        mode: str = "memory",
        path: Path | None = None,
        collection_name: str = "logops_knowledge",
        dim: int = 256,
        embedder: EmbedderAdapter | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.dim = dim
        self.embedder = embedder or EmbedderAdapter(backend="local", dim=dim)
        if mode == "local" and path is not None:
            path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))
        else:
            self.client = QdrantClient(location=":memory:")
        self._chunk_map: dict[str, KnowledgeChunk] = {}

    def build_index(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunk_map = {c.chunk_id: c for c in chunks}
        if self.client.collection_exists(self.collection_name):
            self.client.delete_collection(self.collection_name)

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
        )
        if not chunks:
            return

        texts = [
            f"{c.title} {c.service} {c.error_code} {' '.join(c.keywords)} {c.content}"
            for c in chunks
        ]
        vectors = self.embedder.embed_batch_sync(texts)
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, c.chunk_id)),
                vector=vec,
                payload={"chunk_id": c.chunk_id, "doc_id": c.doc_id, "service": c.service},
            )
            for c, vec in zip(chunks, vectors, strict=True)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)

    def search(self, query: str, top_k: int = 10) -> list[tuple[KnowledgeChunk, float]]:
        if not self._chunk_map:
            return []
        q_vec = self.embedder.embed_batch_sync([query])[0]
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=q_vec,
            limit=top_k,
        )
        results: list[tuple[KnowledgeChunk, float]] = []
        for pt in response.points:
            payload = pt.payload or {}
            cid = payload.get("chunk_id")
            if cid and cid in self._chunk_map:
                results.append((self._chunk_map[cid], float(pt.score)))
        return results
