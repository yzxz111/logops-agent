---
doc_id: KB-017
title: JVM Full GC 频繁 STW 停顿卡顿
service: payment-service
error_code: JVM-GC-STW
severity: P1
keywords: Full GC, GC overhead limit exceeded, STW, G1GC, Allocation Failure, 停顿
---
# JVM Full GC 频繁 STW 停顿卡顿

## 现象描述
`payment-service` 周期性出现 3~8 秒接口无响应，上游网关报 504，监控显示老年代占用接近 100%，GC 日志高频出现 `Full GC (Allocation Failure)` 或 `GC overhead limit exceeded`。

## 根因分析
1. 堆内存分配过小（`-Xmx` 不足），存活对象占比长期超过 80%，导致 G1GC 退化为单线程串行 Full GC（Stop-The-World）。
2. 大对象（Humongous Object > Region/2）频繁创建并直接进入老年代，触发并发标记失败。
3. 元空间（Metaspace）动态类加载泄漏触发 Full GC。

## 排查步骤
1. 在 `payment-service` 日志中搜索 `GC overhead`、`STW` 或耗时突增的请求窗口。
2. 核对启动参数 `-Xms/-Xmx` 与 `-XX:G1HeapRegionSize`，检查代码中是否有超大 JSON 字符串序列化缓存。

## 修复与高危操作提示
- 合理调大 `-Xms/-Xmx` 至容器内存限制的 70%，增加 `-XX:MaxGCPauseMillis=200` 并减少大数组临时分配。
- 高危操作（需人工确认）：线上直接执行 `jmap -dump:live` 会触发一次强制 Full GC 导致服务瞬时卡死，须在摘流后或经人工确认执行。
