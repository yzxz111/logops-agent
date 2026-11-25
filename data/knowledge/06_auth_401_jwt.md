---
doc_id: KB-006
title: 认证服务 401 JWT 过期与签名校验失败
service: auth-service
error_code: AUTH-401
severity: P1
keywords: 401, Unauthorized, ExpiredJwtException, SignatureException, JWT, Token过期
---
# 认证服务 401 JWT 过期与签名校验失败

## 现象描述
用户请求返回 `HTTP 401 Unauthorized`，`auth-service` 日志出现 `io.jsonwebtoken.ExpiredJwtException` 或 `SignatureException: JWT signature does not match locally computed signature`。

## 根因分析
1. 密钥轮换后，网关与 `auth-service` 配置的 `jwt.secret` 或公钥版本不一致，导致签名验签全部失败。
2. 客户端未正确处理 Refresh Token 自动续期，携带已过期 Access Token 持续请求。
3. 集群节点间 NTP 时钟漂移超过 60 秒，导致刚签发的 Token 在另一节点被判定为 `nbf` 未生效或已过期。

## 排查步骤
1. 检索 `auth-service` 日志中的 `ExpiredJwtException` 与 `SignatureException`，区分是过期还是验签不匹配。
2. 使用 `search_source_code` 查看 `JwtTokenValidator.java` 中的密钥加载路径与 `clockSkewSeconds` 容忍配置。
3. 核对各容器节点系统时间同步状态。

## 修复与高危操作提示
- 在密钥轮换期支持双密钥平滑过渡（按 `kid` 匹配旧/新公钥），并配置 `allowedClockSkewSeconds=30`。
- 注意：排查日志中的 `Bearer eyJ...` 必须经过脱敏，严禁明文打印用户 JWT。
