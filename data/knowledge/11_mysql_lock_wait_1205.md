---
doc_id: KB-011
title: MySQL 锁等待超时 Lock wait timeout exceeded 1205
service: inventory-service
error_code: MYSQL-1205
severity: P1
keywords: 1205, Lock wait timeout exceeded, CannotAcquireLockException, 行锁等待, 长事务
---
# MySQL 锁等待超时 Lock wait timeout exceeded 1205

## 现象描述
库存扣减接口报错 `java.sql.SQLException: Lock wait timeout exceeded; try restarting transaction`（错误码 1205）。

## 根因分析
1. 热点 SKU（秒杀商品）并发更新同一行库存记录，行锁竞争激烈，排队时间超过 `innodb_lock_wait_timeout`（默认 50 秒）。
2. 存在未提交的超大事务或后台批处理事务长期持有行锁未释放。

## 排查步骤
1. 在 `inventory-service` 日志中检索 `Lock wait timeout exceeded` 和热点 `sku_id`。
2. 检查数据库 `information_schema.innodb_trx` 是否存在运行超过 30 秒的未提交事务。

## 修复与高危操作提示
- 热点库存改用 Redis 原子预扣减 + 异步落库，或采用库存分段锁降低单行热点争用。
- 高危操作（需人工确认）：`KILL <trx_mysql_thread_id>` 强杀阻塞源事务会导致该事务回滚，须确认业务影响后人工确认执行。
