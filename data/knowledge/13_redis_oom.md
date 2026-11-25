---
doc_id: KB-013
title: Redis 内存打满 OOM command not allowed
service: cache-service
error_code: REDIS-OOM
severity: P0
keywords: OOM command not allowed, RedisDataAccessException, maxmemory, 内存打满, 大Key
---
# Redis 内存打满 OOM command not allowed

## 现象描述
写入缓存或写入分布式锁时报错 `io.lettuce.core.RedisCommandExecutionException: OOM command not allowed when used memory > 'maxmemory'`。

## 根因分析
1. 缓存 Key 未设置 TTL 过期时间，历史冷数据持续堆积撑爆 `maxmemory`。
2. 存在超大 Hash/List/ZSet 大 Key（BigKey），且淘汰策略配置为 `noeviction`。
3. 短时间内大量热点统计日志或会话对象写入未做淘汰保护。

## 排查步骤
1. 在相关服务日志中搜索 `OOM command not allowed` 与具体写入的 Key 前缀。
2. 检索源码中 `RedisTemplate.opsFor...` 调用是否遗漏 `expire` 或 `Duration` 参数。

## 修复与高危操作提示
- 为所有非持久化业务缓存强制补充合理 TTL，非核心缓存实例调整淘汰策略为 `allkeys-lru`。
- 高危操作（需人工确认）：**严禁直接执行 `FLUSHALL` 或 `FLUSHDB`** 清空 Redis 内存，大 Key 清理应使用 `UNLINK` 渐进删除并经人工确认。
