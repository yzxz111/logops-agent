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
    (re.compile(r"504|gateway\s*timeout|upstream\s*timed\s*out|没及时回包|未及时回包|上游.*超时|转圈等待", re.I), "gateway 504 upstream timeout ReadTimeoutException response-timeout"),
    (re.compile(r"502|bad\s*gateway|connection\s*refused|PrematureClose|旧连接.*关|连接.*提前关|滚动发版.*断开", re.I), "gateway 502 BadGateway PrematureCloseException Connection refused upstream"),
    (re.compile(r"429|too\s*many\s*requests|rate\s*limit|突发流量|额度.*打满|(?<!关闭)(?<!关掉)限流(?!关)", re.I), "gateway 429 TooManyRequests RateLimit Sentinel RedisRateLimiter 限流"),
    (re.compile(r"401|jwt|token\s*expired|unauthorized|签名不对|令牌.*有效|登录校验", re.I), "auth-service 401 Unauthorized ExpiredJwtException SignatureException JWT"),
    (re.compile(r"403|accessdenied|rbac|权限不足", re.I), "auth-service 403 Forbidden AccessDeniedException RBAC"),
    (re.compile(r"hikari|druid|connection\s*is\s*not\s*available|连接池|拿不到.*连接|数据库连接.*卡", re.I), "order-service HikariPool Connection is not available SQLTransientConnectionException 连接池耗尽"),
    (re.compile(r"deadlock|1213|死锁|并发抢锁|互相卡住.*回滚", re.I), "order-service mysql deadlock 1213 DeadlockLoserDataAccessException 死锁"),
    (re.compile(r"1205|lock\s*wait\s*timeout", re.I), "inventory-service mysql 1205 Lock wait timeout"),
    (re.compile(r"full\s*gc|gc\s*overhead|stw|堆内存回收|回收停顿|卡死.*秒", re.I), "payment-service Full GC STW G1GC Allocation Failure GC overhead limit exceeded"),
    (re.compile(r"outofmemory|heap\s*space|导出.*内存|oom(?!killed)", re.I), "order-service jvm oom outofmemoryerror heap space 内存溢出"),
    (re.compile(r"redis|jedis|lettuce|oom\s*command\s*not\s*allowed|穿透|雪崩|缓存.*过期|缓存失效", re.I), "redis 缓存雪崩 缓存击穿 热点Key maxmemory inventory-service cache-service"),
    (re.compile(r"thread\s*pool|rejectedexecution|线程池|队列塞满|拒绝执行", re.I), "payment-service ThreadPoolExecutor RejectedExecutionException AbortPolicy 线程池打满"),
    (re.compile(r"kafka|consumer|rebalance|offset|积压|堆积|短信延迟|消息延迟|通知太慢", re.I), "notification-service kafka consumer rebalance CommitFailedException lag 消息积压"),
    (re.compile(r"幂等|重复回调|重复扣款|连续记了两笔|重复入账|duplicatekey", re.I), "payment-service 支付回调 幂等性 重复扣款 DuplicateKeyException"),
    (re.compile(r"redisson|分布式锁|提前释放|illegalmonitorstate", re.I), "inventory-service Redisson 分布式锁 WatchDog leaseTime"),
    (re.compile(r"nacos|eureka|no\s*instances\s*available|注册中心", re.I), "gateway nacos 注册中心 服务不可用 ServiceUnavailableException"),
    (re.compile(r"crashloopbackoff|oomkilled|exit\s*code\s*137|\bpod\b", re.I), "payment-service kubernetes pod oomkilled 137 DirectMemory"),
    (re.compile(r"pkix|sslhandshake|certificateexpired|证书过期", re.I), "gateway tls ssl PKIX CertificateExpiredException 证书过期"),
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
    rewritten_queries: list[str] | None = None,
    top_k: int = 5,
) -> list[ScoredChunk]:
    """基于 RRF 基础分 + 错误码/服务/关键词精确命中及改写语义锚点加权进行重排。"""
    expanded_text = " ".join(rewritten_queries or [])
    q_lower = query.lower()
    exp_lower = expanded_text.lower()
    q_tokens = set(tokenize_mixed(query, expand_synonyms=False))
    exp_tokens = set(tokenize_mixed(expanded_text, expand_synonyms=False)) - q_tokens

    # 归一化 RRF 得分
    max_rrf = max((c.rrf_score for c in candidates), default=1.0) or 1.0

    for item in candidates:
        chunk = item.chunk
        base = item.rrf_score / max_rrf

        bonus = 0.0
        # 1. 错误码精确匹配加权（原始输入优先，改写语义锚点次之）
        err_code_low = chunk.error_code.lower()
        if err_code_low and err_code_low in q_lower:
            bonus += 0.35
        elif err_code_low and err_code_low in exp_lower:
            bonus += 0.25
        else:
            code_nums = re.findall(r"\d{3,4}", err_code_low)
            if any(num in q_lower for num in code_nums):
                bonus += 0.25
            elif any(num in exp_lower for num in code_nums):
                bonus += 0.18

        # 2. 服务名匹配加权
        svc_low = chunk.service.lower()
        if service_hint and svc_low == service_hint.lower():
            bonus += 0.20
        elif svc_low and svc_low in q_lower:
            bonus += 0.15
        elif svc_low and svc_low in exp_lower:
            bonus += 0.14

        # 3. 关键词覆盖率加权（原始词 + 改写扩展词）
        kw_tokens = set()
        for kw in chunk.keywords:
            kw_tokens.update(tokenize_mixed(kw, expand_synonyms=False))
        if kw_tokens:
            denom = max(1, min(len(kw_tokens), 6))
            if q_tokens:
                bonus += 0.25 * (len(kw_tokens & q_tokens) / denom)
            if exp_tokens:
                bonus += 0.20 * (len(kw_tokens & exp_tokens) / denom)

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
