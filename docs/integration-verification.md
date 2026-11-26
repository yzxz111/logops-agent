# LogOps-Agent 端到端联调与真实模型验证记录

本文档记录 `LogOps-Agent` 与本地 Java 模型网关 `yijia-ai-platform` 以及公共 OpenAI 兼容真实模型的端到端联调实测结果（验证时间：`2026-11-26`）。

---

## 1. 对接本地 Java 模型网关 `yijia-ai-platform` 全链路闭环

### 联调配置（脱敏）
- **Provider**: `LLM_PROVIDER=gateway`
- **Gateway Base URL**: `http://127.0.0.1:18081/v1`（Nginx -> Spring Cloud Gateway -> Auth/Quota/RateLimit -> WireMock 渠道）
- **Model**: `chat-standard`
- **API Key 前缀**: `sk-yzh-Ssj48ezF***`

### 实测输入
- `query`: `刚做完滚动发版那几分钟接口偶发报错断开，怀疑旧连接被提前关掉`（无精确英文异常类名与状态码，对应评测集 `CASE-32`）
- `X-Request-ID`: `verify-yijia-gw-20261126`

### 实测结果
- **Agent 状态机**: `status=completed`，`step_count=5`，`token_used=1699`
- **RAG Top-1 命中**: `KB-002`（网关 502 Bad Gateway 下游连接拒绝或重置）
- **报告生成**: 成功包含 `### 5. 模型深度分析补充` 段落（来自本地网关 `chat-standard` 渠道响应）
- **网关侧真实计费与审计日志**（`gateway-service.log`）：

```json
{
  "@timestamp": "2026-11-26T21:13:43.0018256+08:00",
  "message": "gateway_request_completed",
  "logger_name": "com.yuzhihuihe.apiplatform.gateway.openai.DatabaseUsageLogWriter",
  "traceId": "req_cc03348e42cd420da64cdf82d7903a5a",
  "requestId": "req_cc03348e42cd420da64cdf82d7903a5a",
  "reservationId": "f3b65dd1-c136-4aee-90a7-e580bb29375c",
  "apiKeyPrefix": "sk-yzh-Ssj48ezF",
  "model": "chat-standard",
  "httpStatus": 200,
  "outcome": "SUCCEEDED"
}
```

---

## 2. 真实大模型端到端诊断验证（OpenAI 兼容接口）

### 联调配置（脱敏）
- **Provider**: `LLM_PROVIDER=openai`
- **Model**: `gpt-5.6`
- **Request-ID**: `verify-real-llm-002`

### 实测输入
- `query`: `gateway 网关请求 /api/v1/orders/create 频繁报 HTTP 504 ReadTimeoutException，trace=req-gw-1001`

### 实测结果
- **Agent 状态机**: `status=completed`，`step_count=5`，`token_used=22904`（含真实大模型 `usage` 计数）
- **模型深度分析表现**：
  - 结合 `data/mock_source/gateway/application-gateway.yml` 与 `data/mock_logs/gateway.log` 精准区分本次 `req-gw-1001`（504）与无关同文件日志 `req-gw-1002`（502）。
  - 给出按路由灰度调整 `response-timeout`（避免全局放大导致连接池耗尽）及独立排查 `order-service` 慢查询/锁等待的可执行修复建议，并主动提示配置中 `max-idle-time: 65000ms` 大于下游 Tomcat 60s keep-alive 的潜在风险。
