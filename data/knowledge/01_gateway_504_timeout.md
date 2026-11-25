---
doc_id: KB-001
title: 网关 504 Upstream Timeout 上游响应超时
service: gateway
error_code: GATEWAY-504
severity: P0
keywords: 504, GatewayTimeout, ReadTimeoutException, upstream timed out, Netty, response-timeout
---
# 网关 504 Upstream Timeout 上游响应超时

## 现象描述
客户端请求 API 网关返回 `HTTP 504 Gateway Timeout`，网关日志出现 `io.netty.handler.timeout.ReadTimeoutException` 或 `upstream timed out (110: Connection timed out)`。

## 根因分析
1. 网关路由配置的 `response-timeout`（默认 3000ms）小于下游业务接口（如 `order-service` 创建订单或外部支付调用）实际 P99 耗时。
2. 下游服务发生慢 SQL 或线程池阻塞，导致响应时间飙升，拖垮网关 Netty Worker 线程。
3. 网关连接池未开启空闲连接保活探活，复用已被对端关闭的半开连接触发超时。

## 排查步骤
1. 使用 `query_service_logs` 查询 `gateway` 服务包含 `504` 或 `ReadTimeoutException` 的记录，定位具体下游路由与 `trace_id`。
2. 沿 `trace_id` 查询对应下游服务（如 `order-service`）日志，确认耗时卡在数据库还是外部 RPC。
3. 使用 `search_source_code` 检查网关 `application-gateway.yml` 中的 `response-timeout` 与 `connect-timeout`。

## 修复与高危操作提示
- 短期优化：针对慢接口开启局部超时调整与降级熔断策略，避免全局放大超时导致雪崩。
- 高危操作（需人工确认）：若需执行 `kubectl rollout restart deployment/api-gateway` 或修改全局超时阈值，需先评估上游并发积压风险并经人工确认。
