---
doc_id: KB-008
title: 认证会话丢失导致频繁重登
service: auth-service
error_code: AUTH-SESSION-401
severity: P1
keywords: Session丢失, RedisSession, OAuth2, 401, 频繁掉线, Cookie SameSite
---
# 认证会话丢失导致频繁重登

## 现象描述
多实例部署后用户登录后很快再次收到 401 跳转登录页，日志显示 `SessionNotFoundException: Session id xxx not found in Redis`。

## 根因分析
1. 未启用 Spring Session Redis 集中存储，会话仅保存在单机 JVM 内存中，请求被负载均衡到其他实例即失效。
2. Cookie 的 `SameSite=Strict` 或 `Domain` 配置错误，导致跨子域调用未携带 Session Cookie。
3. Redis 开启了 `volatile-lru` 淘汰策略，会话 Key 在内存紧张时被提前驱逐。

## 排查步骤
1. 查询 `auth-service` 日志中 `SessionNotFoundException` 出现的实例 IP 与客户端 User-Agent。
2. 检索源码中的 `SessionConfig` 和 `CookieSerializer` 配置。

## 修复与高危操作提示
- 统一使用 Redis 存储会话并设置独立的会话 Redis 实例（`noeviction` 策略），规范 Cookie `Domain` 与 `SameSite=Lax`。
