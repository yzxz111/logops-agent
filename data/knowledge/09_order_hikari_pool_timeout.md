---
doc_id: KB-009
title: 订单服务 HikariCP 数据库连接池耗尽超时
service: order-service
error_code: DB-POOL-TIMEOUT
severity: P0
keywords: HikariPool, Connection is not available, SQLTransientConnectionException, 连接池耗尽, Druid
---
# 订单服务 HikariCP 数据库连接池耗尽超时

## 现象描述
订单创建接口大面积报错 `java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms`。

## 根因分析
1. 长事务内部包含外部 HTTP/RPC 调用（如在 `@Transactional` 内同步调用支付或风控接口），导致数据库连接被长时间占用无法归还连接池。
2. 慢查询堆积占满 `maximum-pool-size`（例如默认 10 或 20），后续请求排队超过 `connection-timeout`。
3. 手动获取 `Connection` 后未在 `finally` 块关闭导致连接泄漏。

## 排查步骤
1. 使用 `query_service_logs` 查询 `order-service` 中的 `HikariPool-1` 和 `Connection is not available`。
2. 开启 `leak-detection-threshold` 定位未及时归还连接的代码调用栈。
3. 使用 `search_source_code` 检查 `OrderService.java` 中 `@Transactional` 方法内是否嵌套了外部 RPC 调用。

## 修复与高危操作提示
- 将 `@Transactional` 范围缩小至纯数据库操作，外部 RPC 移出事务外，并适当调整 `maximum-pool-size`。
- 高危操作（需人工确认）：在数据库端批量 `KILL` 长时间睡眠连接或强行重启 DB 前，需经过 DBA 人工确认。
