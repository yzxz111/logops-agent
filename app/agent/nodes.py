"""LangGraph 各状态机节点实现：异常提取、RAG/MCP 协同、相关性评估、二次检索、高危确认与报告生成。"""

from __future__ import annotations

import re
from typing import Any

from langgraph.types import interrupt

from app.agent.state import AgentState
from app.config import Settings
from app.context.compressor import compress_tool_result, extract_error_window
from app.context.sanitizer import sanitize_text
from app.gateway_client.client import GatewayClient, estimate_tokens
from app.mcp_tools.schemas import LogQueryInput, SourceSearchInput
from app.mcp_tools.tools import query_service_logs, search_source_code
from app.rag.pipeline import HybridRagPipeline

_KNOWN_SERVICES = [
    "gateway",
    "order-service",
    "auth-service",
    "payment-service",
    "inventory-service",
    "cache-service",
    "notification-service",
]

_SERVICE_KEYWORDS: dict[str, list[str]] = {
    "gateway": ["网关", "gateway", "504", "502", "429", "503", "413", "nacos", "pkix", "ssl", "tls", "ratelimit", "发版", "旧连接", "没及时回包", "未及时回包", "突发流量"],
    "order-service": ["订单", "order", "hikari", "1213", "deadlock", "慢查询", "slowquery", "outofmemory", "heap", "kafka producer", "数据库连接", "抢锁"],
    "auth-service": ["认证", "登录", "鉴权", "auth", "jwt", "401", "403", "rbac", "session", "令牌", "签名"],
    "payment-service": ["支付", "payment", "pay", "full gc", "stw", "137", "oomkilled", "rejectedexecution", "线程池", "回调", "幂等", "内存回收", "队列塞满", "两笔账"],
    "inventory-service": ["库存", "inventory", "sku", "1205", "lock wait", "缓存雪崩", "击穿", "redisson", "分布式锁", "watch dog", "缓存同时过期"],
    "cache-service": ["redis", "cache", "oom command", "maxmemory", "lettuce", "jedis", "keys *"],
    "notification-service": ["通知", "短信", "notification", "rebalance", "commitfailed", "积压", "lag", "consumer", "消息堆积"],
}

_SOURCE_HINT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"504|ReadTimeout|response-timeout", re.I), "response-timeout"),
    (re.compile(r"502|PrematureClose|max-idle-time", re.I), "max-idle-time"),
    (re.compile(r"429|RateLimit|令牌桶", re.I), "RequestRateLimiter"),
    (re.compile(r"503|CircuitBreaker|熔断", re.I), "CircuitBreaker"),
    (re.compile(r"Hikari|连接池|Transactional|createOrder", re.I), "createOrder"),
    (re.compile(r"OutOfMemory|heap space|导出", re.I), "exportAllOrders"),
    (re.compile(r"Redisson|WatchDog|IllegalMonitorState|分布式锁", re.I), "tryLock"),
    (re.compile(r"JWT|SignatureException|ExpiredJwt|401", re.I), "parseClaims"),
    (re.compile(r"RejectedExecution|线程池", re.I), "ThreadPoolExecutor"),
    (re.compile(r"KEYS\s*\*|RedisCommandTimeout|scanInvalidKeys", re.I), "redisTemplate.keys"),
    (re.compile(r"Rebalance|CommitFailed|max\.poll", re.I), "max-poll-records"),
]

_HIGH_RISK_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bFLUSHALL\b|\bFLUSHDB\b", re.I), "redis_flush", "清空 Redis 全库缓存 (FLUSHALL/FLUSHDB)"),
    (re.compile(r"kubectl\s+delete\s+pod|kubectl\s+rollout\s+restart", re.I), "k8s_pod_op", "强行删除或重启生产 Pod (kubectl delete/restart)"),
    (re.compile(r"\bkill\s+-9\b", re.I), "force_kill", "强制终止服务进程 (kill -9)"),
    (re.compile(r"\bDROP\s+(?:TABLE|INDEX)\b|\bALTER\s+TABLE\b", re.I), "ddl_mutation", "线上数据库 DDL 结构变更 (DROP/ALTER)"),
    (re.compile(r"--reset-offsets|to-latest", re.I), "kafka_offset_reset", "重置 Kafka 消费位点（可能导致消息丢失）"),
    (re.compile(r"关闭限流|rate_limit\s*=\s*0|无限大", re.I), "disable_ratelimit", "关闭或清零网关限流保护"),
    (re.compile(r"TrustAll|跳过\s*SSL|关闭证书校验", re.I), "disable_tls", "禁用生产环境 TLS/SSL 证书校验"),
]

_TRACE_ID_RE = re.compile(r"\b(req-[a-z]+-\d+|[a-f0-9]{16,32})\b", re.I)
_ERROR_CODE_RE = re.compile(r"\b(401|403|404|413|429|500|502|503|504|1205|1213|137)\b")
_EXCEPTION_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Exception|Error))\b")


def _check_circuit_breaker(state: AgentState) -> str:
    """检查步数与 Token 预算是否触发熔断。"""
    if state.get("step_count", 0) >= state.get("max_steps", 8):
        return "max_steps_exceeded"
    if state.get("token_used", 0) >= state.get("token_budget", 6000):
        return "token_budget_exceeded"
    return ""


def _infer_service(text: str) -> str:
    lowered = text.lower()
    for svc in _KNOWN_SERVICES:
        if svc in lowered:
            return svc
    best_svc = ""
    best_score = 0
    for svc, kws in _SERVICE_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in lowered)
        if score > best_score:
            best_score = score
            best_svc = svc
    return best_svc


def _infer_source_keyword(text: str) -> str:
    for pattern, kw in _SOURCE_HINT_PATTERNS:
        if pattern.search(text):
            return kw
    exc_match = _EXCEPTION_RE.search(text)
    if exc_match:
        return exc_match.group(1)
    return ""


def _detect_high_risk_actions(text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for pattern, action_id, desc in _HIGH_RISK_PATTERNS:
        if pattern.search(text) and action_id not in seen_ids:
            seen_ids.add(action_id)
            found.append({"action_id": action_id, "description": desc})
    return found


class AgentNodes:
    """封装 LangGraph 节点依赖（RAG 引擎、网关客户端与配置）。"""

    def __init__(
        self,
        settings: Settings,
        rag_pipeline: HybridRagPipeline,
        gateway_client: GatewayClient,
    ) -> None:
        self.settings = settings
        self.rag = rag_pipeline
        self.gateway = gateway_client

    def extract_anomaly(self, state: AgentState) -> dict[str, Any]:
        """节点 1：敏感信息脱敏、长堆栈压缩与异常信号提取。"""
        raw_query = state["raw_query"]
        san_res = sanitize_text(raw_query)
        compressed = extract_error_window(san_res.sanitized_text, max_lines=35)

        service = _infer_service(san_res.sanitized_text)
        error_codes = list(dict.fromkeys(_ERROR_CODE_RE.findall(san_res.sanitized_text)))
        exceptions = list(dict.fromkeys(_EXCEPTION_RE.findall(san_res.sanitized_text)))
        trace_match = _TRACE_ID_RE.search(san_res.sanitized_text)
        trace_id = trace_match.group(1) if trace_match else ""
        source_kw = _infer_source_keyword(san_res.sanitized_text)
        high_risk = _detect_high_risk_actions(san_res.sanitized_text)

        log_kw = ""
        if exceptions:
            log_kw = exceptions[0]
        elif error_codes:
            log_kw = error_codes[0]

        signals = {
            "service": service,
            "error_codes": error_codes,
            "exception_classes": exceptions,
            "trace_id": trace_id,
            "log_keyword": log_kw,
            "source_keyword": source_kw,
        }

        added_tokens = estimate_tokens(compressed) + 80
        step = state.get("step_count", 0) + 1
        tokens = state.get("token_used", 0) + added_tokens
        events = list(state.get("trace_events", []))
        events.append({
            "step": step,
            "node": "extract_anomaly",
            "signals": signals,
            "redactions": san_res.redaction_counts,
        })

        next_state: dict[str, Any] = {
            "sanitized_query": san_res.sanitized_text,
            "compressed_query": compressed,
            "redaction_counts": san_res.redaction_counts,
            "extracted_signals": signals,
            "high_risk_actions": high_risk,
            "requires_human_confirm": bool(high_risk),
            "step_count": step,
            "token_used": tokens,
            "trace_events": events,
        }
        breaker = _check_circuit_breaker({**state, **next_state})
        if breaker:
            next_state["circuit_breaker_reason"] = breaker
        return next_state

    def retrieve_and_tools(self, state: AgentState) -> dict[str, Any]:
        """节点 2：混合 RAG 检索（BM25+Qdrant+RRF）并协同调用只读 MCP 工具。"""
        signals = state.get("extracted_signals", {})
        service = signals.get("service", "")
        query_text = state.get("compressed_query") or state["sanitized_query"]

        rag_res = self.rag.search(
            query_text,
            top_k=5,
            mode="agentic",
            service_hint=service,
        )
        citations = [c.model_dump() for c in rag_res.citations]

        # 若未推断出服务名，则用 Top1 RAG 命中的服务名辅助工具调用
        inferred_svc = service or (citations[0]["service"] if citations else "")
        tool_calls = list(state.get("tool_calls", []))
        tool_chunks: list[str] = []
        added_tokens = 0

        # 1. 调用只读日志工具
        if inferred_svc:
            log_kw = signals.get("log_keyword", "")
            trace_id = signals.get("trace_id", "")
            log_input = LogQueryInput(
                service=inferred_svc,
                keyword=log_kw,
                trace_id=trace_id,
                window_lines=4,
                max_matches=3,
            )
            log_res = query_service_logs(log_input, logs_dir=self.settings.mock_logs_dir)
            raw_chars = sum(len(s.content) for s in log_res.slices)
            comp_chars = len(log_res.compressed_summary)
            tool_calls.append({
                "tool": "query_service_logs",
                "args": log_input.model_dump(),
                "total_matches": log_res.total_matches,
                "raw_chars": raw_chars,
                "compressed_chars": comp_chars,
                "locations": [
                    {
                        "path": f"data/mock_logs/{s.file}",
                        "start_line": s.start_line,
                        "end_line": s.end_line,
                        "matched_line": s.matched_line,
                    }
                    for s in log_res.slices
                ],
            })
            if log_res.compressed_summary:
                tool_chunks.append(f"### 日志切片 ({inferred_svc})\n{log_res.compressed_summary}")
                added_tokens += estimate_tokens(log_res.compressed_summary)

        # 2. 调用只读源码检索工具
        src_kw = signals.get("source_keyword", "")
        if not src_kw and citations:
            src_kw = _infer_source_keyword(citations[0].get("snippet", ""))
        if src_kw:
            src_input = SourceSearchInput(
                keyword=src_kw,
                service=inferred_svc if inferred_svc in {"gateway", "order-service", "auth-service", "payment-service", "inventory-service", "cache-service", "notification-service"} else "",
                context_lines=4,
                max_matches=3,
            )
            src_res = search_source_code(src_input, source_dir=self.settings.mock_source_dir)
            raw_chars = sum(len(m.snippet) for m in src_res.matches)
            comp_chars = len(src_res.compressed_summary)
            tool_calls.append({
                "tool": "search_source_code",
                "args": src_input.model_dump(),
                "total_matches": src_res.total_matches,
                "raw_chars": raw_chars,
                "compressed_chars": comp_chars,
                "locations": [
                    {
                        "path": f"data/mock_source/{m.file}",
                        "start_line": m.start_line,
                        "end_line": m.end_line,
                        "matched_line": m.matched_line,
                    }
                    for m in src_res.matches
                ],
            })
            if src_res.compressed_summary:
                tool_chunks.append(f"### 源码片段 ({src_kw})\n{src_res.compressed_summary}")
                added_tokens += estimate_tokens(src_res.compressed_summary)

        combined_tool_ctx = "\n\n".join(tool_chunks)
        for c in citations[:3]:
            added_tokens += estimate_tokens(c.get("snippet", ""))

        step = state.get("step_count", 0) + 1
        tokens = state.get("token_used", 0) + max(120, added_tokens)
        events = list(state.get("trace_events", []))
        events.append({
            "step": step,
            "node": "retrieve_and_tools",
            "rag_hits": len(citations),
            "top_doc_id": citations[0]["doc_id"] if citations else None,
            "tools_invoked": [t["tool"] for t in tool_calls],
        })

        next_state: dict[str, Any] = {
            "rewritten_queries": rag_res.rewritten_queries,
            "rag_citations": citations,
            "tool_calls": tool_calls,
            "tool_context": combined_tool_ctx,
            "step_count": step,
            "token_used": tokens,
            "trace_events": events,
        }
        breaker = _check_circuit_breaker({**state, **next_state})
        if breaker:
            next_state["circuit_breaker_reason"] = breaker
        return next_state

    def evaluate_relevance(self, state: AgentState) -> dict[str, Any]:
        """节点 3：相关性判断节点，决定是否需要触发二次检索。"""
        citations = state.get("rag_citations", [])
        top_score = float(citations[0]["score"]) if citations else 0.0
        tool_calls = state.get("tool_calls", [])
        tool_hit = any(tc.get("total_matches", 0) > 0 for tc in tool_calls)

        # 若同时命中知识库高分和工具证据则置信度提升；反之模糊输入导致工具未命中且得分偏低时触发二次检索
        relevance = top_score + (0.12 if tool_hit else -0.05)
        relevance = round(max(0.0, min(1.0, relevance)), 4)
        is_relevant = relevance >= self.settings.agent_relevance_threshold and bool(citations)

        step = state.get("step_count", 0) + 1
        tokens = state.get("token_used", 0) + 40
        events = list(state.get("trace_events", []))
        events.append({
            "step": step,
            "node": "evaluate_relevance",
            "relevance_score": relevance,
            "is_relevant": is_relevant,
            "retry_count": state.get("retry_count", 0),
        })

        next_state: dict[str, Any] = {
            "relevance_score": relevance,
            "is_relevant": is_relevant,
            "step_count": step,
            "token_used": tokens,
            "trace_events": events,
        }
        breaker = _check_circuit_breaker({**state, **next_state})
        if breaker:
            next_state["circuit_breaker_reason"] = breaker
        return next_state

    def rewrite_and_retry(self, state: AgentState) -> dict[str, Any]:
        """节点 4：Query 扩展改写 + 二次混合检索与日志补充定位。"""
        signals = state.get("extracted_signals", {})
        base_q = state.get("compressed_query") or state["sanitized_query"]
        tool_ctx = state.get("tool_context", "")

        # 从工具输出或错误码补充扩展关键词
        extra_terms: list[str] = []
        for match in _EXCEPTION_RE.finditer(tool_ctx):
            extra_terms.append(match.group(1))
        for match in _ERROR_CODE_RE.finditer(tool_ctx):
            extra_terms.append(match.group(1))

        # 针对模糊中文描述补充排查语义锚点
        if not extra_terms:
            if "卡" in base_q or "慢" in base_q or "等" in base_q:
                extra_terms.extend(["timeout", "504", "HikariPool", "Full GC", "slow"])
            elif "登录" in base_q or "掉线" in base_q or "验证" in base_q:
                extra_terms.extend(["401", "JWT", "SessionNotFoundException", "auth-service"])
            elif "重复" in base_q or "扣款" in base_q or "超卖" in base_q:
                extra_terms.extend(["幂等", "Redisson", "DuplicateKeyException", "分布式锁"])
            else:
                extra_terms.extend(["Exception", "Error", "timeout", "503"])

        expanded_query = f"{base_q} {' '.join(dict.fromkeys(extra_terms))}".strip()
        rag_res = self.rag.search(
            expanded_query,
            top_k=5,
            mode="agentic",
            service_hint=signals.get("service", ""),
        )
        citations = [c.model_dump() for c in rag_res.citations]

        # 若此前未命中日志，使用 Top1 文档所属服务补查一次日志
        tool_calls = list(state.get("tool_calls", []))
        if citations and not tool_ctx:
            fallback_svc = citations[0]["service"]
            log_input = LogQueryInput(
                service=fallback_svc,
                keyword="",
                window_lines=4,
                max_matches=2,
            )
            log_res = query_service_logs(log_input, logs_dir=self.settings.mock_logs_dir)
            tool_calls.append({
                "tool": "query_service_logs",
                "args": log_input.model_dump(),
                "total_matches": log_res.total_matches,
                "raw_chars": sum(len(s.content) for s in log_res.slices),
                "compressed_chars": len(log_res.compressed_summary),
                "locations": [
                    {
                        "path": f"data/mock_logs/{s.file}",
                        "start_line": s.start_line,
                        "end_line": s.end_line,
                        "matched_line": s.matched_line,
                    }
                    for s in log_res.slices
                ],
            })
            if log_res.compressed_summary:
                tool_ctx = f"### 二次检索补充日志 ({fallback_svc})\n{log_res.compressed_summary}"

        step = state.get("step_count", 0) + 1
        tokens = state.get("token_used", 0) + 160 + estimate_tokens(tool_ctx)
        retry = state.get("retry_count", 0) + 1
        events = list(state.get("trace_events", []))
        events.append({
            "step": step,
            "node": "rewrite_and_retry",
            "retry_count": retry,
            "expanded_query": expanded_query,
            "rag_hits": len(citations),
        })

        next_state: dict[str, Any] = {
            "rewritten_queries": list(dict.fromkeys(state.get("rewritten_queries", []) + rag_res.rewritten_queries)),
            "rag_citations": citations,
            "tool_calls": tool_calls,
            "tool_context": tool_ctx,
            "retry_count": retry,
            "step_count": step,
            "token_used": tokens,
            "trace_events": events,
        }
        breaker = _check_circuit_breaker({**state, **next_state})
        if breaker:
            next_state["circuit_breaker_reason"] = breaker
        return next_state

    def high_risk_check(self, state: AgentState) -> dict[str, Any]:
        """节点 5：检测修复路径或请求是否涉及高危运维指令。"""
        actions = list(state.get("high_risk_actions", []))
        seen = {a["action_id"] for a in actions}
        # 仅当用户查询文本本身已包含或明确询问高危指令时触发确认；
        # 若只是检索到的手册中作为禁止警示提及，不强制阻塞正常查询，但会在报告中保留警示。
        for act in _detect_high_risk_actions(state.get("sanitized_query", "")):
            if act["action_id"] not in seen:
                actions.append(act)
                seen.add(act["action_id"])

        requires = bool(actions)
        step = state.get("step_count", 0) + 1
        tokens = state.get("token_used", 0) + 30
        events = list(state.get("trace_events", []))
        events.append({
            "step": step,
            "node": "high_risk_check",
            "requires_human_confirm": requires,
            "actions": actions,
        })

        next_state: dict[str, Any] = {
            "high_risk_actions": actions,
            "requires_human_confirm": requires,
            "step_count": step,
            "token_used": tokens,
            "trace_events": events,
        }
        breaker = _check_circuit_breaker({**state, **next_state})
        if breaker:
            next_state["circuit_breaker_reason"] = breaker
        return next_state

    def human_confirm(self, state: AgentState) -> dict[str, Any]:
        """节点 6：人工确认节点（利用 LangGraph interrupt 暂停等待确认）。"""
        actions = state.get("high_risk_actions", [])
        decision = interrupt({
            "type": "human_confirm_required",
            "thread_id": state.get("thread_id", ""),
            "request_id": state.get("request_id", ""),
            "message": "检测到高危运维操作，请人工确认是否批准执行或降级为只读建议。",
            "high_risk_actions": actions,
        })
        approved = bool(decision.get("approved", False)) if isinstance(decision, dict) else bool(decision)
        comment = decision.get("comment", "") if isinstance(decision, dict) else ""

        step = state.get("step_count", 0) + 1
        events = list(state.get("trace_events", []))
        events.append({
            "step": step,
            "node": "human_confirm",
            "approved": approved,
            "comment": comment,
        })
        return {
            "human_approved": approved,
            "human_comment": comment,
            "step_count": step,
            "trace_events": events,
        }

    async def generate_report(self, state: AgentState) -> dict[str, Any]:
        """节点 7：生成结构化根因定位与溯源报告（支持对接网关 LLM 或确定性模板）。"""
        citations = state.get("rag_citations", [])
        tool_calls = state.get("tool_calls", [])
        tool_context = state.get("tool_context", "")
        breaker = state.get("circuit_breaker_reason", "")
        high_risk = state.get("high_risk_actions", [])
        approved = state.get("human_approved")
        redactions = state.get("redaction_counts", {})
        signals = state.get("extracted_signals", {})

        top_doc = citations[0] if citations else None
        root_cause = (
            f"[{top_doc['doc_id']}] {top_doc['title']} (服务: {top_doc['service']}, 错误码: {top_doc['error_code']})"
            if top_doc
            else "暂未匹配到高置信度历史故障手册，建议结合日志与链路追踪进一步人工排查。"
        )

        # 构建离线结构化报告作为基线及安全兜底
        citation_lines = "\n".join(
            f"- `[{c['doc_id']}]` **{c['title']}** | 章节: `{c['section']}` | 来源: `{c['source_path']}#{c['line_range']}` | 相关度: `{c['score']}`"
            for c in citations[:3]
        ) or "- 暂无匹配知识库条目"

        tool_lines = "\n".join(
            f"- `{t['tool']}`({t['args']}) -> 命中 `{t['total_matches']}` 条"
            + (f"（压缩: {t['raw_chars']} -> {t['compressed_chars']} 字符）" if t.get("raw_chars") else "")
            for t in tool_calls
        ) or "- 未触发外部只读工具调用"

        risk_section = ""
        if high_risk:
            risk_items = "\n".join(f"- **{a['action_id']}**: {a['description']}" for a in high_risk)
            if approved is True:
                risk_status = f"已获人工确认批准执行（备注: {state.get('human_comment') or '无'}）。"
            elif approved is False:
                risk_status = f"人工已拒绝高危操作（备注: {state.get('human_comment') or '无'}），已降级为只读排查与低风险替代建议。"
            else:
                risk_status = "高危操作尚未获得人工确认，禁止直接执行。"
            risk_section = f"\n### 高危指令安全审计\n{risk_items}\n- **确认状态**: {risk_status}\n"

        breaker_banner = (
            f"> **[熔断降级提示]** 状态机触发保护阈值 `{breaker}`（步数: {state.get('step_count', 0)}/{state.get('max_steps', 8)}，Token: {state.get('token_used', 0)}/{state.get('token_budget', 6000)}），以下为基于已收集证据的阶段性诊断结果。\n\n"
            if breaker
            else ""
        )

        redaction_note = (
            f"已自动脱敏敏感字段: {redactions}" if redactions else "未检测到明文敏感信息"
        )

        report_text = (
            f"{breaker_banner}"
            f"## LogOps 智能排障根因报告\n\n"
            f"- **Request-ID**: `{state.get('request_id', '')}`\n"
            f"- **识别服务**: `{signals.get('service') or (top_doc['service'] if top_doc else 'unknown')}`\n"
            f"- **核心异常信号**: 错误码 `{signals.get('error_codes', [])}` | 异常类 `{signals.get('exception_classes', [])}`\n"
            f"- **隐私脱敏审计**: {redaction_note}\n\n"
            f"### 1. 根因定位结论\n{root_cause}\n\n"
            f"### 2. 知识库引用溯源 (BM25 + Qdrant RRF)\n{citation_lines}\n\n"
            f"### 3. 只读 MCP 工具取证\n{tool_lines}\n"
            f"{risk_section}"
        )

        if tool_context:
            report_text += f"\n### 4. 脱敏压缩后的关键现场证据\n{tool_context}\n"

        # 当配置为真实网关/OpenAI且未触发熔断时，请求大模型进行深度根因综合润色
        extra_llm_tokens = 0
        if self.settings.llm_provider != "mock" and not breaker:
            prompt = (
                "你是资深后端与网关 SRE 排障专家。请根据以下脱敏输入、知识库溯源与只读日志/源码证据，"
                "用简洁准确的中文输出根因结论、关键证据链与安全修复建议（不要编造未提供的文件或行号）。\n\n"
                f"用户故障描述:\n{state.get('compressed_query', '')}\n\n"
                f"已汇总结构化证据:\n{report_text}"
            )
            try:
                resp = await self.gateway.chat_completions(
                    [{"role": "user", "content": prompt}],
                    request_id=state.get("request_id"),
                    max_tokens=800,
                )
                extra_llm_tokens = resp.usage.total_tokens
                if resp.content.strip():
                    report_text = f"{report_text}\n### 5. 模型深度分析补充\n{resp.content.strip()}\n"
            except Exception:
                # 网关调用失败时保留确定性结构化报告
                pass

        step = state.get("step_count", 0) + 1
        tokens = state.get("token_used", 0) + estimate_tokens(report_text) + extra_llm_tokens
        final_status = "circuit_broken" if breaker else "completed"
        events = list(state.get("trace_events", []))
        events.append({
            "step": step,
            "node": "generate_report",
            "status": final_status,
            "token_used": tokens,
        })

        return {
            "root_cause": root_cause,
            "final_report": report_text,
            "status": final_status,
            "step_count": step,
            "token_used": tokens,
            "trace_events": events,
        }
