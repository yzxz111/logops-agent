---
doc_id: KB-014
title: Redis 缓存雪崩与热点 Key 击穿导致 DB 崩溃
service: inventory-service
error_code: REDIS-AVALANCHE
severity: P0
keywords: 缓存雪崩, 缓存击穿, 缓存穿透, 热点Key, 布隆过滤器, 互斥锁
---
# Redis 缓存雪崩与热点 Key 击穿导致 DB 崩溃

## 现象描述
整点时刻大量商品缓存同时失效或某个爆款 SKU 失效瞬间，数据库 QPS 暴涨 10 倍，引发连锁超时。

## 根因分析
1. 批量预热缓存设置了相同的固定 TTL（如 3600s），导致同一秒集体失效（缓存雪崩）。
2. 热点 Key 失效瞬间没有互斥锁/逻辑过期保护，数千并发直接穿透回源查询 MySQL（缓存击穿）。
3. 恶意请求查询不存在的 ID，每次穿透到 DB（缓存穿透）。

## 排查步骤
1. 检查 `inventory-service` 日志中同一秒涌入的回源 DB 查询告警。
2. 检索源码中的缓存读取封装类，查看是否设置随机 TTL 抖动和分布式互斥锁重建逻辑。

## 修复与高危操作提示
- 在基础 TTL 上增加随机抖动（`3600 + random(0, 600)`）；对热点 Key 采用逻辑过期或本地 Caffeine 二级缓存；对空值进行短 TTL 缓存或引入布隆过滤器。
