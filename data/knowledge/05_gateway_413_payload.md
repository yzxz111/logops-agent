---
doc_id: KB-005
title: 网关 413 Payload Too Large 请求体超限
service: gateway
error_code: GATEWAY-413
severity: P2
keywords: 413, PayloadTooLarge, DataBufferLimitException, Exceeded limit, max-in-memory-size
---
# 网关 413 Payload Too Large 请求体超限

## 现象描述
批量导入或长日志上报接口报错 `HTTP 413 Payload Too Large`，Spring Cloud Gateway 抛出 `org.springframework.core.io.buffer.DataBufferLimitException: Exceeded limit on max bytes to buffer`。

## 根因分析
1. Spring WebFlux 默认 `max-in-memory-size` 仅 256KB，大报文或长堆栈未做压缩直接透传导致缓冲区溢出。
2. Nginx 侧 `client_max_body_size` 默认 1MB，上传附件或大 JSON 时被前端代理拦截。

## 排查步骤
1. 查看 `gateway` 日志中 `DataBufferLimitException` 出现的 URI 与请求体字节数。
2. 检查网关配置文件中的 `spring.codec.max-in-memory-size` 及路由过滤器是否缓存了全量 Body。

## 修复与高危操作提示
- 在请求侧启用上下文摘要压缩或 Gzip，并在网关按路由合理调整 `max-in-memory-size`（如 4MB），避免全局放开引起 OOM。
