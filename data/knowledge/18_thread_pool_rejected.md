---
doc_id: KB-018
title: 线程池打满 RejectedExecutionException 任务被拒绝
service: payment-service
error_code: THREAD-POOL-FULL
severity: P0
keywords: RejectedExecutionException, ThreadPoolExecutor, AbortPolicy, 线程池打满, 队列溢出
---
# 线程池打满 RejectedExecutionException 任务被拒绝

## 现象描述
异步通知或并行风控校验抛出 `java.util.concurrent.RejectedExecutionException: Task rejected from ThreadPoolExecutor`，核心线程和队列全部占满。

## 根因分析
1. 阻塞型 I/O 任务提交到了自定义业务线程池，下游慢响应导致工作线程全部挂起，任务队列迅速溢出。
2. 核心线程数 `corePoolSize` / 最大线程数 `maximumPoolSize` 配置过小，且使用了默认的 `AbortPolicy` 拒绝策略。
3. 子任务嵌套提交到同一个线程池引发“线程饥饿死锁”（父任务等子任务，子任务在队列等父任务释放线程）。

## 排查步骤
1. 检索 `payment-service` 日志中的 `RejectedExecutionException` 与线程池名字（如 `pay-async-pool`）。
2. 使用 `search_source_code` 检查 `ThreadPoolExecutor` 的初始化参数、队列容量及拒绝策略，确认是否存在父子任务共用池。

## 修复与高危操作提示
- 隔离 IO 密集型与 CPU 密集型线程池，父子异步任务使用不同线程池避免饥饿死锁，针对可降级任务改用 `CallerRunsPolicy` 或异步告警落盘。
