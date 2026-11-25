---
doc_id: KB-019
title: Kafka 消费者 Rebalance 风暴与消息积压
service: notification-service
error_code: KAFKA-REBALANCE
severity: P1
keywords: Kafka, Rebalance, CommitFailedException, max.poll.interval.ms, 消息积压, lag
---
# Kafka 消费者 Rebalance 风暴与消息积压

## 现象描述
Kafka 消费组延迟（Consumer Lag）持续飙升，日志反复打印 `CommitFailedException: Commit cannot be completed since the group has already rebalanced` 和 `Revoking previously assigned partitions`。

## 根因分析
1. 单批拉取消息过多（`max.poll.records=500`），且业务消费逻辑（如调用短信/邮件接口）耗时过长，两次 `poll()` 间隔超过 `max.poll.interval.ms`（默认 5 分钟），Broker 认为消费者假死将其踢出消费组，触发持续 Rebalance。
2. 消费者未处理异常导致容器频繁重启或心跳线程阻塞。

## 排查步骤
1. 查询 `notification-service` 日志中的 `CommitFailedException` 或 `rebalanced`。
2. 使用 `search_source_code` 检查 KafkaConsumer 配置（`max.poll.records`, `max.poll.interval.ms`, `session.timeout.ms`）。

## 修复与高危操作提示
- 调小单次拉取条数 `max.poll.records=50`，适当调大 `max.poll.interval.ms`，将耗时外部调用改为批量并发或死信队列异步重试。
- 高危操作（需人工确认）：直接重置消费位点 `--reset-offsets --to-latest` 跳过积压消息会导致通知丢失，必须经人工确认。
