---
doc_id: KB-007
title: 权限中心 403 RBAC 鉴权拒绝
service: auth-service
error_code: AUTH-403
severity: P2
keywords: 403, Forbidden, AccessDeniedException, RBAC, 权限不足, 角色映射
---
# 权限中心 403 RBAC 鉴权拒绝

## 现象描述
已登录用户访问新上线接口返回 `HTTP 403 Forbidden`，日志打印 `org.springframework.security.access.AccessDeniedException: Access is denied`。

## 根因分析
1. 新接口路径未同步写入 RBAC 权限菜单表或网关白名单配置遗漏。
2. Redis 中缓存的用户角色权限集合未在授权变更后主动失效，存在脏缓存。
3. 网关透传给下游的 `X-User-Roles` Header 格式（逗号分隔 vs JSON 数组）与下游解析器不一致。

## 排查步骤
1. 检索 `auth-service` 日志中的 `AccessDeniedException`，确认被拦截的 URI 与当前用户缺失的 `permission_code`。
2. 对比 `search_source_code` 中 `@PreAuthorize` 注解权限标识与权限配置表是否一致。

## 修复与高危操作提示
- 补齐角色-接口权限绑定并清理对应用户权限缓存 Key（`auth:perm:{userId}`）。
- 高危操作（需人工确认）：禁止使用 `FLUSHALL` 清空整个 Redis 来刷新权限缓存，必须精确删除指定 Key。
