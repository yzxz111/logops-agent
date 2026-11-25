---
doc_id: KB-022
title: Kubernetes Pod OOMKilled Exit Code 137 容器被强杀
service: payment-service
error_code: K8S-OOM-137
severity: P0
keywords: OOMKilled, Exit Code 137, cgroup, memory limit, DirectMemory, 容器重启
---
# Kubernetes Pod OOMKilled Exit Code 137 容器被强杀

## 现象描述
容器频繁重启，`kubectl describe pod` 状态显示 `Last State: Terminated, Reason: OOMKilled, Exit Code: 137`，但应用日志内并未见到 Java Heap OOM。

## 根因分析
1. JVM `-Xmx` 设置过高（例如容器 `limits.memory=2Gi` 但 `-Xmx1800m`），加上 Metaspace、线程栈、Netty 堆外直接内存（DirectMemory）和 JNI 开销后突破 cgroup 内存上限，触发 Linux Kernel OOM Killer 发送 `SIGKILL (137)`。
2. 未开启 `-XX:MaxDirectMemorySize` 限制，Netty 零拷贝缓冲区持续膨胀。

## 排查步骤
1. 检索服务重启前的 `payment-service` 日志，确认是否出现 `OutOfDirectMemoryError` 或高并发报文分配。
2. 检查部署清单或源码启动脚本中的 JVM 内存参数占比。

## 修复与高危操作提示
- 严格控制 `-Xmx` 不超过容器 `limits.memory` 的 65%~70%，显式设置 `-XX:MaxDirectMemorySize=256m` 与 `-XX:MaxRAMPercentage=70.0`。
- 高危操作（需人工确认）：直接执行 `kubectl delete pod --force --grace-period=0` 或调大生产集群节点超卖比例须经人工确认。
