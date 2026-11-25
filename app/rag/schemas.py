"""RAG 知识块与溯源引用数据模型。"""

from typing import Literal

from pydantic import BaseModel, Field

SearchMode = Literal["bm25_only", "vector_only", "hybrid_rrf", "agentic"]


class KnowledgeChunk(BaseModel):
    """知识库分块单元（按服务与错误码结构化切分）。"""

    chunk_id: str
    doc_id: str
    title: str
    service: str
    error_code: str
    severity: str = "P1"
    section: str
    content: str
    source_path: str
    line_start: int
    line_end: int
    keywords: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    """返回给前端/报告的溯源引用字段。"""

    chunk_id: str
    doc_id: str
    title: str
    service: str
    error_code: str
    section: str
    source_path: str
    line_range: str
    score: float
    snippet: str


class ScoredChunk(BaseModel):
    """带检索明细得分的分块。"""

    chunk: KnowledgeChunk
    bm25_score: float = 0.0
    vector_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0


class RagSearchResult(BaseModel):
    """混合检索完整结果，含溯源信息与改写查询。"""

    original_query: str
    rewritten_queries: list[str] = Field(default_factory=list)
    mode: SearchMode = "agentic"
    hits: list[ScoredChunk] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
