---
doc_id: KB-020
title: Kafka 发送超时与分区 Leader 不可用
service: order-service
error_code: KAFKA-SEND-TIMEOUT
severity: P1
keywords: Kafka, TimeoutException, NotLeaderOrFollowerException, acks, Expiring batches
---
# Kafka 发送超时与分区 Leader 不可用

## 现象描述
订单创建后发送领域事件失败，日志出现 `org.apache.kafka.common.errors.TimeoutException: Expiring 12 record(s) for order-events-0` 或 `NotLeaderOrFollowerException`。

## 根因分析
1. Kafka Broker 节点磁盘满或网络隔离导致分区 Leader 切换未完成，`acks=all` 等待 ISR 副本同步超时。
2. 生产者 `request.timeout.ms` 或 `delivery.timeout.ms` 过小，且未配置重试次数 `retries`。

## 排查步骤
1. 在 `order-service` 日志中定位 `Expiring` 或 `NotLeaderOrFollowerException`。
2. 检索源码中的 `KafkaProducerConfig`，查看 `acks`、`retries` 与超时时间，确认是否有本地事务消息表兜底。

## 修复与高危操作提示
- 引入本地消息表 + 定时补偿投递机制确保事件最终一致性，开启幂等生产 `enable.idempotence=true`。
