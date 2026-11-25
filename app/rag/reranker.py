"""Query 改写器、RRF 倒数排名融合与轻量重排器。"""

from __future__ import annotations

import re

from app.rag.embedder import tokenize_mixed
from app.rag.schemas import KnowledgeChunk, ScoredChunk

_ERROR_CODE_RE = re.compile(
    r"\b(?:HTTP\s*)?(401|403|404|429|500|502|503|504|1213|1040|2002)\b|"
    r"\b([A-Z]+-\d{3,4})\b|"
    r"\b([A-Z][a-zA-Z]+(?:Exception|Error))\b"
)

_REWRITE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"504|gateway\s*timeout|upstream\s*timed\s*out", re.I), "gateway 504 upstream timeout readTimeout 超时"),
    (re.compile(r"502|bad\s*gateway|connection\s*refused", re.I), "gateway 502 bad gateway upstream 连接拒绝"),
    (re.compile(r"429|too\s*many\s*requests|限流|rate\s*limit", re.I), "429 rate limit sentinel 令牌桶 限流"),
    (re.compile(r"401|jwt|token\s*expired|unauthorized", re.I), "auth 401 jwt token 过期 签名校验失败"),
    (re.compile(r"hikari|druid|connection\s*is\s*not\s*available|连接池", re.I), "mysql 连接池耗尽 hikari druid timeout"),
    (re.compile(r"deadlock|1213|lock\s*wait", re.I), "mysql deadlock 1213 死锁 事务回滚"),
    (re.compile(r"outofmemory|heap\s*space|gc\s*overhead|oom", re.I), "jvm oom outofmemoryerror gc heap 内存溢出"),
    (re.compile(r"redis|jedis|lettuce|oom\s*command\s*not\s*allowed|穿透|雪崩", re.I), "redis 缓存异常 连接池 内存上限"),
    (re.compile(r"kafka|consumer|rebalance|offset|积压|堆积|短信延迟|消息延迟", re.I), "kafka consumer rebalance lag 消息积压 notification-service"),
    (re.compile(r"nacos|eureka|no\s*instances\s*available|注册中心", re.I), "nacos 注册中心 服务不可用 心跳超时"),
    (re.compile(r"crashloopbackoff|oomkilled|exit\s*code\s*137|pod", re.I), "kubernetes pod oomkilled 137 crashloopbackoff"),
    (re.compile(r"thread\s*pool|rejectedexecution|线程池", re.I), "线程池打满 RejectedExecutionException 队列溢出"),
]


class QueryRewriter:
    """多路故障 Query 改写器：提取核心异常信号 + 生成语义扩展检索句。"""

    def rewrite(self, query: str, *, service_hint: str = "") -> list[str]:
        queries: list[str] = [query.strip()]

        # 提取错误码与异常类名组成紧凑信号 Query
        signals: list[str] = []
        for match in _ERROR_CODE_RE.finditer(query):
            for grp in match.groups():
                if grp:
                    signals.append(grp)
        if service_hint:
            signals.append(service_hint)
        if signals:
            compact = " ".join(dict.fromkeys(signals))
            if compact not in queries:
                queries.append(compact)

        # 基于运维故障模式扩展同义术语 Query
        for pattern, expansion in _REWRITE_RULES:
            if pattern.search(query):
                expanded = f"{expansion} {service_hint}".strip()
                if expanded not in queries:
                    queries.append(expanded)

        return queries[:4]


def reciprocal_rank_fusion(
    bm25_lists: list[list[tuple[KnowledgeChunk, float]]],
    vector_lists: list[list[tuple[KnowledgeChunk, float]]],
    *,
    k: int = 60,
    bm25_weight: float = 1.15,
    vector_weight: float = 1.0,
) -> list[ScoredChunk]:
    """多路 BM25 + 向量检索结果 RRF 融合。"""
    merged: dict[str, ScoredChunk] = {}

    def _accumulate(
        ranked_lists: list[list[tuple[KnowledgeChunk, float]]],
        weight: float,
        is_bm25: bool,
    ) -> None:
        for ranked in ranked_lists:
            for rank, (chunk, raw_score) in enumerate(ranked, start=1):
                entry = merged.get(chunk.chunk_id)
                if entry is None:
                    entry = ScoredChunk(chunk=chunk)
                    merged[chunk.chunk_id] = entry
                rrf_delta = weight * (1.0 / (k + rank))
                entry.rrf_score += rrf_delta
                if is_bm25:
                    entry.bm25_score = max(entry.bm25_score, raw_score)
                else:
                    entry.vector_score = max(entry.vector_score, raw_score)

    _accumulate(bm25_lists, bm25_weight, is_bm25=True)
    _accumulate(vector_lists, vector_weight, is_bm25=False)

    return sorted(merged.values(), key=lambda x: x.rrf_score, reverse=True)


def rerank_candidates(
    query: str,
    candidates: list[ScoredChunk],
    *,
    service_hint: str = "",
    top_k: int = 5,
) -> list[ScoredChunk]:
    """基于 RRF 基础分 + 错误码/服务/关键词精确命中加权进行重排。"""
    q_lower = query.lower()
    q_tokens = set(tokenize_mixed(query, expand_synonyms=False))

    # 归一化 RRF 得分
    max_rrf = max((c.rrf_score for c in candidates), default=1.0) or 1.0

    for item in candidates:
        chunk = item.chunk
        base = item.rrf_score / max_rrf

        bonus = 0.0
        # 1. 错误码精确匹配加权
        err_code_low = chunk.error_code.lower()
        if err_code_low and err_code_low in q_lower:
            bonus += 0.35
        else:
            # 检查纯数字状态码匹配（如 GATEWAY-504 中的 504）
            code_nums = re.findall(r"\d{3,4}", err_code_low)
            if any(num in q_lower for num in code_nums):
                bonus += 0.25

        # 2. 服务名匹配加权
        svc_low = chunk.service.lower()
        if service_hint and svc_low == service_hint.lower():
            bonus += 0.20
        elif svc_low and svc_low in q_lower:
            bonus += 0.15

        # 3. 关键词覆盖率加权
        kw_tokens = set()
        for kw in chunk.keywords:
            kw_tokens.update(tokenize_mixed(kw, expand_synonyms=False))
        if kw_tokens and q_tokens:
            overlap = len(kw_tokens & q_tokens) / max(1, min(len(kw_tokens), 6))
            bonus += 0.25 * overlap

        # 4. 章节优先级（根因分析与排查步骤略微优先）
        if any(tag in chunk.section for tag in ("根因", "现象", "排查", "修复")):
            bonus += 0.05

        item.rerank_score = round(min(1.0, 0.55 * base + bonus), 4)

    ranked = sorted(candidates, key=lambda x: x.rerank_score, reverse=True)
    # 按 doc_id 控制文档多样性：同一故障手册最多保留 1 个最优分块进入 Top-K，避免单篇手册占满上下文
    deduped: list[ScoredChunk] = []
    seen_docs: set[str] = set()
    for item in ranked:
        if item.chunk.doc_id in seen_docs:
            continue
        seen_docs.add(item.chunk.doc_id)
        deduped.append(item)
        if len(deduped) >= top_k:
            break
    return deduped
