---
doc_id: KB-012
title: MySQL 慢查询全表扫描导致 CPU 飙高
service: order-service
error_code: MYSQL-SLOW-QUERY
severity: P1
keywords: 慢查询, SlowQuery, 全表扫描, 索引失效, 隐式转换, CPU 100%
---
# MySQL 慢查询全表扫描导致 CPU 飙高

## 现象描述
数据库 CPU 持续 95%+，订单列表查询接口耗时从 20ms 恶化到 8s 以上，并伴随连接池打满。

## 根因分析
1. 查询条件字段存在隐式类型转换（如 `varchar` 类型的 `order_no` 传入纯数字未加引号），导致 B+Tree 索引失效退化为全表扫描。
2. `LIKE '%keyword'` 左模糊查询或对索引列使用 `DATE_FORMAT(create_time, ...)` 函数。
3. 深分页 `LIMIT 1000000, 20` 扫描大量无效行。

## 排查步骤
1. 查看 `order-service` 日志中耗时超过 2000ms 的 SQL 告警记录。
2. 使用 `search_source_code` 检查 Mapper XML / Repository 中的动态 SQL 拼接与分页写法。

## 修复与高危操作提示
- 消除隐式类型转换与索引列函数包裹，改用游标分页（`WHERE id > last_id LIMIT 20`）。
- 高危操作（需人工确认）：大表在线 `ALTER TABLE ADD INDEX` 可能引发元数据锁（MDL）阻塞全表读写，须走 gh-ost/pt-osc 并经人工确认。
