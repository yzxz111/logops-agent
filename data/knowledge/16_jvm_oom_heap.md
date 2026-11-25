---
doc_id: KB-016
title: JVM 堆内存溢出 OutOfMemoryError Java heap space
service: order-service
error_code: JVM-OOM-HEAP
severity: P0
keywords: OutOfMemoryError, Java heap space, HeapDump, 内存泄漏, ThreadLocal, 大对象导出
---
# JVM 堆内存溢出 OutOfMemoryError Java heap space

## 现象描述
应用日志突然大量打印 `java.lang.OutOfMemoryError: Java heap space`，接口全面无响应，容器可能随后重启。

## 根因分析
1. 导出报表或批量查询未限制分页大小，一次性将数十万条记录加载到 `ArrayList` 中撑爆老年代。
2. `ThreadLocal` 变量在线程池复用线程中未调用 `remove()`，导致大对象长期被强引用无法回收。
3. 本地缓存（如无界 `ConcurrentHashMap`）持续写入无淘汰机制引发内存泄漏。

## 排查步骤
1. 查询 `order-service` 日志中首次出现 `OutOfMemoryError` 前的业务操作记录（如导出、批量同步）。
2. 使用 `search_source_code` 定位无界查询或 `ThreadLocal` / 静态 `Map` 缓存定义。

## 修复与高危操作提示
- 导出改为流式游标分页（EasyExcel 分批写），规范在 `finally` 中调用 `ThreadLocal.remove()`，配置 `-XX:+HeapDumpOnOutOfMemoryError`。
- 高危操作（需人工确认）：直接执行 `kill -9` 杀掉进程会丢失现场且未完成请求数据可能异常，转储 HeapDump 并重启前须人工确认。
