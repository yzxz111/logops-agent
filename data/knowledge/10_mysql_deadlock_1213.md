---
doc_id: KB-010
title: MySQL 事务死锁 Deadlock found 1213
service: order-service
error_code: MYSQL-1213
severity: P1
keywords: Deadlock, 1213, DeadlockLoserDataAccessException, 死锁, 加锁顺序, InnoDB
---
# MySQL 事务死锁 Deadlock found 1213

## 现象描述
高并发下单或库存扣减时日志抛出 `com.mysql.cj.jdbc.exceptions.MySQLTransactionRollbackException: Deadlock found when trying to get lock; try restarting transaction`（错误码 1213）。

## 根因分析
1. 两个并发事务以相反的顺序锁定多行记录（例如事务 A 先锁订单再锁库存，事务 B 先锁库存再锁订单）。
2. 批量更新语句未按主键升序排序，导致行锁获取顺序交错。
3. 辅助索引范围更新触发 Gap Lock（间隙锁）相互等待。

## 排查步骤
1. 检索 `order-service` 日志中 `Deadlock found` 及关联的 SQL 业务方法名。
2. 使用 `search_source_code` 定位多表更新或批量扣减逻辑，检查锁资源顺序是否一致。

## 修复与高危操作提示
- 统一所有并发事务的资源加锁顺序（如按 `sku_id` 升序加锁），并在服务层对 `DeadlockLoserDataAccessException` 增加幂等重试。
- 高危操作（需人工确认）：禁止线上直接执行 `DROP INDEX` 或关闭 InnoDB 死锁检测（`innodb_deadlock_detect=OFF`）而不做压测评估，需人工确认。
