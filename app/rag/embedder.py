"""中英文双粒度本地哈希向量编码器 & 可选网关 Embeddings 适配器。"""

from __future__ import annotations

import hashlib
import re

import numpy as np

from app.gateway_client.client import GatewayClient

_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]+")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[_.-]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")

# 常见运维故障语义同义簇，提升本地稠密向量的语义对齐能力
_SEMANTIC_SYNONYMS: dict[str, list[str]] = {
    "超时": ["timeout", "timedout", "504", "readtimeout", "connecttimeout"],
    "回包": ["timeout", "504", "readtimeout", "upstream"],
    "timeout": ["超时", "504", "阻塞", "卡顿"],
    "发版": ["502", "prematureclose", "badgateway", "upstream"],
    "断开": ["502", "prematureclose", "connection", "504"],
    "限流": ["429", "ratelimit", "toomanyrequests", "sentinel", "throttled"],
    "突发": ["429", "ratelimit", "toomanyrequests", "配额"],
    "额度": ["429", "ratelimit", "配额", "令牌桶"],
    "429": ["限流", "ratelimit", "熔断", "降级"],
    "内存": ["oom", "outofmemoryerror", "heap", "gc", "metaspace"],
    "回收": ["gc", "fullgc", "stw", "allocation"],
    "停顿": ["stw", "gc", "fullgc", "卡顿"],
    "oom": ["内存溢出", "heap", "gc", "outofmemory"],
    "连接池": ["hikari", "druid", "pool", "connection", "getconnection"],
    "连接": ["hikari", "pool", "connection", "502"],
    "死锁": ["deadlock", "1213", "lockwait", "事务锁"],
    "抢锁": ["deadlock", "1213", "事务", "回滚"],
    "熔断": ["circuitbreaker", "503", "fallback", "降级"],
    "认证": ["401", "jwt", "token", "unauthorized", "签名过期"],
    "令牌": ["401", "jwt", "token", "signature", "expired"],
    "签名": ["401", "jwt", "signatureexception", "token"],
    "权限": ["403", "forbidden", "rbac", "鉴权失败"],
    "网关": ["gateway", "502", "504", "badgateway", "upstream"],
    "缓存": ["redis", "穿透", "雪崩", "击穿", "jedis", "lettuce"],
    "雪崩": ["redis", "缓存雪崩", "热点key", "avalanche"],
    "线程池": ["threadpool", "rejectedexecution", "队列溢出", "abortpolicy"],
    "队列": ["threadpool", "rejectedexecution", "线程池打满"],
    "消息队列": ["kafka", "rebalance", "lag", "consumer", "积压"],
    "回调": ["幂等", "duplicatekey", "重复扣款", "支付回调"],
    "重复": ["幂等", "duplicatekey", "重复扣款", "支付"],
    "注册中心": ["nacos", "eureka", "服务下线", "心跳超时"],
}


def tokenize_mixed(text: str, *, expand_synonyms: bool = False) -> list[str]:
    """中英文混合分词：保留错误码/类名原串、驼峰拆分词以及中文 uni-gram / bi-gram。"""
    tokens: list[str] = []
    lowered = text.lower()

    for m in _ASCII_TOKEN_RE.findall(text):
        m_low = m.lower()
        tokens.append(m_low)
        parts = [p.lower() for p in _CAMEL_SPLIT_RE.split(m) if len(p) >= 2]
        if len(parts) > 1:
            tokens.extend(parts)

    for seg in _CJK_RE.findall(lowered):
        if len(seg) == 1:
            tokens.append(seg)
            continue
        for i in range(len(seg)):
            tokens.append(seg[i])
            if i + 1 < len(seg):
                tokens.append(seg[i : i + 2])
            if i + 2 < len(seg):
                tokens.append(seg[i : i + 3])

    if expand_synonyms:
        extra: list[str] = []
        for tok in tokens:
            if tok in _SEMANTIC_SYNONYMS:
                extra.extend(_SEMANTIC_SYNONYMS[tok])
        tokens.extend(extra)

    return tokens


class LocalHashEmbedder:
    """确定性本地哈希稠密向量器（零外部依赖，支持特征哈希与语义同义扩展）。"""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed_one(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = tokenize_mixed(text, expand_synonyms=True)
        if not tokens:
            vec[0] = 1.0
            return vec.tolist()

        for tok in tokens:
            digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
            raw_int = int.from_bytes(digest, "little")
            idx = raw_int % self.dim
            sign = 1.0 if ((raw_int >> 8) & 1) == 0 else -1.0
            weight = 1.6 if (len(tok) >= 3 and tok.isascii()) else 1.0
            vec[idx] += sign * weight

        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class EmbedderAdapter:
    """可切换本地向量与网关 OpenAI 兼容 Embeddings 的适配器。"""

    def __init__(
        self,
        *,
        backend: str = "local",
        dim: int = 256,
        gateway_client: GatewayClient | None = None,
    ) -> None:
        self.backend = backend
        self.local = LocalHashEmbedder(dim=dim)
        self.gateway_client = gateway_client

    async def aembed_batch(self, texts: list[str]) -> list[list[float]]:
        if self.backend == "gateway" and self.gateway_client is not None:
            try:
                return await self.gateway_client.create_embeddings(texts)
            except Exception:
                return self.local.embed_batch(texts)
        return self.local.embed_batch(texts)

    def embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        return self.local.embed_batch(texts)
