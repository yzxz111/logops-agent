---
doc_id: KB-023
title: 支付回调幂等失效导致重复扣款与状态机冲突
service: payment-service
error_code: PAY-IDEMPOTENT-ERR
severity: P0
keywords: 支付回调, 幂等性, 重复扣款, DuplicateKeyException, 状态机冲突, 分布式锁
---
# 支付回调幂等失效导致重复扣款与状态机冲突

## 现象描述
第三方支付渠道重试异步回调时，日志出现 `DuplicateKeyException` 或订单金额被重复入账，用户反馈重复扣款。

## 根因分析
1. 并发回调请求同时进入，代码仅用“先查询 `status == INIT` 再 `UPDATE`”的非原子操作，未利用数据库唯一索引或乐观锁状态机条件更新（`WHERE status = 'INIT'`）。
2. 幂等校验依赖 Redis Key 但未在事务提交后才允许放行，或锁粒度错误。

## 排查步骤
1. 查询 `payment-service` 日志中的 `DuplicateKeyException` 或同一 `trade_no` 的多条回调处理日志。
2. 使用 `search_source_code` 检查 `PaymentCallbackService.java` 的回调处理与状态机更新 SQL。

## 修复与高危操作提示
- 采用“支付流水号唯一约束 + 乐观锁条件更新 `UPDATE pay_order SET status='SUCCESS' WHERE order_no=? AND status='INIT'`”保证严格幂等。
- 高危操作（需人工确认）：涉及资金退款或手工修改支付流水状态 `UPDATE pay_order` 必须经财务与运维双人人工确认。
