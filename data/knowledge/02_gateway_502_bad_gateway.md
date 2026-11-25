---
doc_id: KB-002
title: 网关 502 Bad Gateway 下游连接拒绝或重置
service: gateway
error_code: GATEWAY-502
severity: P0
keywords: 502, BadGateway, Connection refused, PrematureCloseException, upstream, 重置
---
# 网关 502 Bad Gateway 下游连接拒绝或重置

## 现象描述
网关对外批量返回 `HTTP 502 Bad Gateway`，错误日志打印 `reactor.netty.http.client.PrematureCloseException: Connection prematurely closed BEFORE response` 或 `ConnectException: Connection refused`。

## 根因分析
1. 下游微服务实例因 OOM 或滚动发布刚下线，但网关本地 Ribbon/LoadBalancer 实例列表尚未刷新，继续转发请求到已关闭端口。
2. 下游 Tomcat `maxConnections` 或 `acceptCount` 满载后主动发送 TCP RST 断连。
3. 网关 Keep-Alive 空闲超时时间大于下游服务端的 `server.tomcat.keep-alive-timeout`，导致复用失效连接。

## 排查步骤
1. 调用日志工具检索 `gateway` 日志中的 `502`、`PrematureCloseException` 及目标实例 IP:Port。
2. 检查目标服务是否在发布或频繁重启（查看 Pod 事件或 Nacos 实例健康状态）。
3. 检索网关源码中的 `HttpClient` 连接池配置（`maxIdleTime` 应小于下游 Keep-Alive）。

## 修复与高危操作提示
- 建议开启网关针对幂等 GET 请求的有限次重试，并将网关连接池 `maxIdleTime` 调小至 20s。
- 高危操作（需人工确认）：执行 `kubectl delete pod` 强删异常实例前，必须先摘除注册中心流量并经过人工审批。
