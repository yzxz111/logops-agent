---
doc_id: KB-015
title: Redis Lettuce/Jedis 连接池耗尽超时
service: cache-service
error_code: REDIS-POOL-TIMEOUT
severity: P1
keywords: RedisCommandTimeoutException, PoolExhaustedException, Lettuce, Jedis, 连接池耗尽, KEYS
---
# Redis Lettuce/Jedis 连接池耗尽超时

## 现象描述
服务间歇性抛出 `io.lettuce.core.RedisCommandTimeoutException: Command timed out after 2 second(s)` 或 `JedisPoolException: Could not get a resource from the pool`。

## 根因分析
1. 代码中误用了阻塞命令 `KEYS *` 或在单线程 Redis 上执行 O(N) 大集合全量 `HGETALL`，阻塞了所有后续请求。
2. Jedis 模式下借用连接未在 `try-with-resources` 中释放，导致连接泄漏。
3. Lettuce 开启连接池后 `max-active` 过小或网络抖动导致共享连接重连阻塞。

## 排查步骤
1. 在报错服务日志中检索 `RedisCommandTimeoutException` 或 `Could not get a resource`。
2. 使用 `search_source_code` 全局扫描是否存在 `keys(`、`hgetAll(` 或 `SMEMBERS` 等危险慢命令。

## 修复与高危操作提示
- 将 `KEYS` 替换为游标迭代 `SCAN`，拆解大 Hash，并开启 Lettuce `share-native-connection` 或合理配置连接池。
- 高危操作（需人工确认）：禁止在线上业务高峰期执行 `KEYS *` 或 `DEBUG SEGFAULT` 等诊断命令，必须人工确认替代方案。
