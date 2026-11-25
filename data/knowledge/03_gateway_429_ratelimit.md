---
doc_id: KB-003
title: 网关 429 Too Many Requests 限流触发与令牌桶耗尽
service: gateway
error_code: GATEWAY-429
severity: P1
keywords: 429, TooManyRequests, RateLimit, Sentinel, RedisRateLimiter, 限流, 退避
---
# 网关 429 Too Many Requests 限流触发与令牌桶耗尽

## 现象描述
上游调用方或模型网关客户端收到 `HTTP 429 Too Many Requests`，响应头通常携带 `Retry-After`，网关日志记录 `RateLimiterFilter blocked request, replenishRate=100, burstCapacity=200`。

## 根因分析
1. 突发营销流量或上游客户端缺少退避重试（Retry Storm），瞬时 QPS 超过令牌桶 `burstCapacity`。
2. 多租户/单 API Key 维度配额配置过低，未区分关键业务与普通查询接口。
3. 上游重试风暴：收到 429 后未按 `Retry-After` 指数退避，立即并发重发加剧限流。

## 排查步骤
1. 查询 `gateway` 日志中 `429` 和 `RateLimiterFilter` 关键词，确认被限流的路由 ID 与租户标识。
2. 调用源码检索工具定位 `RateLimiterConfig` 或 `TokenBucketLimiter` 阈值定义。
3. 检查上游网关客户端是否配置了 `429` 指数退避（Exponential Backoff + Jitter）。

## 修复与高危操作提示
- 正确做法：客户端启用带抖动的指数退避重试，同时按租户分级配置令牌桶容量。
- 高危操作（需人工确认）：禁止直接执行关闭限流过滤器或将 `replenishRate` 设为无限大（`rate_limit=0` / 清零限流规则），此类修改必须经过人工确认以防压垮后端。
