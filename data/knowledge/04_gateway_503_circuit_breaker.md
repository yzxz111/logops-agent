---
doc_id: KB-004
title: 网关 503 熔断降级 Service Unavailable
service: gateway
error_code: GATEWAY-503
severity: P0
keywords: 503, CircuitBreaker, Resilience4j, CallNotPermittedException, 熔断器打开, 降级
---
# 网关 503 熔断降级 Service Unavailable

## 现象描述
请求大量返回 `HTTP 503 Service Unavailable`，网关堆栈出现 `io.github.resilience4j.circuitbreaker.CallNotPermittedException: CircuitBreaker 'orderServiceCB' is OPEN`。

## 根因分析
1. 下游核心服务错误率或慢调用比例超过熔断器阈值（如 `failureRateThreshold=50%`），熔断器进入 `OPEN` 状态。
2. 滑动窗口过小（如 `slidingWindowSize=10`），少量偶发抖动即触发全量熔断。
3. 熔断降级 Fallback 方法缺失或兜底返回异常。

## 排查步骤
1. 在 `gateway` 日志中搜索 `CallNotPermittedException` 和 `CircuitBreaker` 状态迁移记录（`CLOSED -> OPEN`）。
2. 检查熔断触发前 1 分钟的下游真实异常日志，先解决下游根因再恢复熔断。
3. 使用源码搜索定位 `CircuitBreakerConfig` 参数及 `FallbackController`。

## 修复与高危操作提示
- 应先恢复下游异常服务，待 `HALF_OPEN` 探活自动恢复。
- 高危操作（需人工确认）：强制重置熔断器或下线熔断保护可能直接雪崩下游服务，变更前须人工确认。
