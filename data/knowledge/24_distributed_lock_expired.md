---
doc_id: KB-024
title: Redisson 分布式锁超时提前释放导致并发超卖
service: inventory-service
error_code: LOCK-EXPIRED
severity: P0
keywords: Redisson, 分布式锁, WatchDog, leaseTime, 提前释放, IllegalMonitorStateException
---
# Redisson 分布式锁超时提前释放导致并发超卖

## 现象描述
库存扣减出现超卖或释放锁时抛出 `java.lang.IllegalMonitorStateException: attempt to unlock lock, not locked by current thread`。

## 根因分析
1. 调用 `lock.tryLock(waitTime, leaseTime, TimeUnit.SECONDS)` 时显式传入了正数 `leaseTime`（如 5s），导致 Redisson 看门狗（WatchDog）自动续期机制失效；业务耗时超过 5s 后锁自动过期被其他线程抢占。
2. 释放锁前未判断 `lock.isHeldByCurrentThread()`。

## 排查步骤
1. 检索 `inventory-service` 日志中的 `attempt to unlock lock` 或同一订单的并发锁警告。
2. 使用 `search_source_code` 检查 `InventoryLockService.java` 中 `tryLock` 的传参方式与 `finally` 解锁代码。

## 修复与高危操作提示
- 使用无 `leaseTime` 参数（或 `leaseTime = -1`）启用 WatchDog 自动续期，并在 `finally` 中校验 `if (lock.isLocked() && lock.isHeldByCurrentThread()) lock.unlock()`。
