---
doc_id: KB-021
title: Nacos 注册中心无可用实例 No instances available
service: gateway
error_code: NACOS-NO-INSTANCE
severity: P0
keywords: Nacos, No instances available, 503, 心跳超时, 服务下线, namespace
---
# Nacos 注册中心无可用实例 No instances available

## 现象描述
网关或 Feign 调用报错 `ServiceUnavailableException: Unable to find instance for payment-service` 或 `No instances available for xxx`。

## 根因分析
1. Nacos 客户端与服务端之间网络闪断或服务实例长时间 Full GC，未能在 `15s` 内发送心跳被 Nacos Server 临时摘除（30s 彻底删除）。
2. 发布配置时误将 `spring.cloud.nacos.discovery.namespace` 或 `group` 改错，导致调用方与提供方不在同一命名空间隔离域。
3. 开启了 Nacos 保护阈值或优雅上下线脚本未生效。

## 排查步骤
1. 检索 `gateway` 日志中 `Unable to find instance` 对应的服务名称。
2. 使用 `search_source_code` 核对各服务的 `application.yml` 中 Nacos `namespace` 与 `group` 是否一致。

## 修复与高危操作提示
- 统一配置中心 `namespace` 与 `group`，并配置网关/Feign 本地实例缓存兜底；修复实例健康检查探针。
- 高危操作（需人工确认）：手动在 Nacos 控制台强行下线全量实例或修改集群配置须人工确认。
