# LogOps-Agent 智能排障平台 MVP

基于 **FastAPI (SSE) + LangGraph 状态机 + Agentic Hybrid RAG (BM25 + Qdrant RRF) + 只读 MCP 工具 + 模型网关客户端** 的智能运维排障后端 MVP。

输入故障描述或异常堆栈，系统提取服务、错误码与 Trace ID，结合故障手册、模拟日志和源码片段生成带引用的诊断报告。默认使用本地 Mock 模式，安装依赖后无需模型 API Key、独立 Qdrant 服务或 Java 服务即可演示。

## 项目亮点

- **可追踪的排障流程**：LangGraph 编排异常提取、检索取证、相关性评估、低相关性二次检索和报告生成；通过 SSE 输出节点进度与报告分片。
- **可对比的检索链路**：BM25、本地哈希向量、RRF 融合，以及规则 Query 改写与轻量重排；引用保留文档、章节和行号。
- **只读取证与人工确认**：日志切片、源码定位工具通过 FastMCP 暴露；内置参数校验、路径穿越拦截、敏感字段脱敏和上下文压缩。高危建议进入人工确认流程，系统不执行运维命令。
- **模型网关适配**：提供 OpenAI 兼容客户端，支持 Request-ID 透传、429 退避重试和上游 SSE 解析。
- **可复现验证**：内置 25 篇故障手册、7 个服务的模拟日志、30 条故障评测和 17 项自动化测试。

## 目录结构

```text
logops-agent/
├── app/
│   ├── api/            # FastAPI 流式接口 (SSE)、人工确认恢复接口 & X-Request-ID 透传中间件
│   ├── agent/          # LangGraph 状态机 (异常提取 -> 混合检索/MCP取证 -> 相关性评估/二次检索 -> 高危确认 -> 报告生成 + 步数/Token 熔断)
│   ├── rag/            # Markdown 章节分块、BM25 + Qdrant(本地模式) RRF 混合检索、Query 改写、文档多样性重排与引用溯源
│   ├── mcp_tools/      # 只读 MCP 工具 (日志切片检索、源码关键词定位) + Pydantic 校验 + FastMCP Server
│   ├── context/        # 长堆栈敏感信息脱敏、错误窗口提取与 Tool Result 摘要压缩
│   └── gateway_client/ # 对接 Java「AI 模型接入与网关平台」/ OpenAI 兼容 API（含 429 指数退避、SSE 解析、Request-ID 透传）
├── data/
│   ├── knowledge/      # 25 篇后端与网关常见故障手册 Markdown（125 个分块，含 YAML Frontmatter 元数据）
│   ├── mock_logs/      # 7 个微服务的模拟故障日志
│   └── mock_source/    # 模拟 Java/YAML 故障源码片段
├── eval/               # 30 条故障评测集 + Recall@K / MRR / 工具准确率 / 根因命中率脚本及实测报告
└── tests/              # 17 项 pytest 单元测试与状态机边界测试
```

## 快速开始

### 1. 克隆项目并安装依赖

需要 Python 3.11+；本次验证使用 Python 3.12。Windows PowerShell：

```powershell
git clone https://github.com/yzxz111/logops-agent.git
cd logops-agent
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux / macOS：

```bash
git clone https://github.com/yzxz111/logops-agent.git
cd logops-agent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

### 2. 配置模型网关（可选，默认 `mock` 模式可离线闭环）

在 `.env` 中按需切换提供方；实际密钥仅保存在本地 `.env` 中：
- `LLM_PROVIDER=mock`：默认本地离线模式，依赖安装完成后无需外部模型服务即可跑通流程与评测。
- `LLM_PROVIDER=gateway`：连接 OpenAI 兼容模型网关（设置 `GATEWAY_BASE_URL`、`GATEWAY_API_KEY`、`GATEWAY_MODEL`）。
- `LLM_PROVIDER=openai`：对接公共 OpenAI 兼容模型 API。

### 3. 启动 FastAPI 服务

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
```

启动后打开 `http://127.0.0.1:8000/docs` 体验交互式 API 文档；当前仓库未包含独立前端。

核心接口：
- `GET /health`：健康检查与知识库索引分块统计
- `POST /api/v1/diagnose`：同步智能排障诊断
- `POST /api/v1/diagnose/stream`：SSE 流式诊断（透传 `X-Request-ID`）
- `POST /api/v1/diagnose/{thread_id}/confirm`：高危指令人工确认恢复
- `POST /api/v1/rag/search`：混合 RAG 检索对比调试

PowerShell 诊断示例：

```powershell
$body = @{ query = "gateway 返回 504 ReadTimeoutException trace=req-gw-1001" } | ConvertTo-Json
$result = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/diagnose" `
  -Method Post -ContentType "application/json; charset=utf-8" `
  -Headers @{ "X-Request-ID" = "resume-demo-001" } `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$result.final_report
```

也可通过 `.venv/Scripts/python.exe -m app.mcp_tools.server` 单独启动 stdio MCP 服务；Linux / macOS 使用 `.venv/bin/python`。

### 4. 运行单元测试与 30 条评测集

```powershell
# 运行全部 pytest 单元测试 & 状态机边界测试
.\.venv\Scripts\python.exe -m pytest -v

# 运行 30 条故障评测集并生成 eval/eval_report.json 与 eval/eval_report.md
.\.venv\Scripts\python.exe -m eval.run_eval
```

## 实测结果摘要（30 条评测集 / 17 项 pytest）

以下结果于 **2026-11-25** 在本地 Mock 模式复现。完整报告见 [eval/eval_report.md](eval/eval_report.md)，评测输入和预期结果见 [eval/dataset.json](eval/dataset.json)。

- **pytest 测试**：`17/17` 全部通过（涵盖 429 退避、SSE 解析、Request-ID 透传、RAG 溯源、MCP 路径防穿越、脱敏与压缩、二次检索、步数/Token 熔断、人工确认中断与恢复）。
- **RAG 检索对比（125 个分块）**：
  - `bm25_only`：`Recall@1 = 93.33%`，`Recall@3 = 96.67%`，`Recall@5 = 100.00%`，`MRR = 0.9583`
  - `vector_only`：`Recall@1 = 96.67%`，`Recall@3 = 96.67%`，`Recall@5 = 96.67%`，`MRR = 0.9667`
  - `hybrid_rrf`：`Recall@1 = 96.67%`，`Recall@3 = 96.67%`，`Recall@5 = 96.67%`，`MRR = 0.9667`
  - `agentic`（Query 改写 + 多路 RRF + 文档多样性重排）：`Recall@1 = 96.67%`，`Recall@3 = 100.00%`，`Recall@5 = 100.00%`，`MRR = 0.9833`
- **Agent 全链路能力**：工具调用准确率 `100.00%`、根因命中率 `100.00%`、高危指令人工确认拦截率 `100.00%`、工具上下文压缩率 `21.93%`。

## 实现范围与评测口径

- 这是演示与学习用途的后端 MVP。故障手册、日志、源码片段和评测集均为仓库内的演示材料，日志中的账号、手机号及密钥形状字符串用于脱敏测试。
- 30 条评测使用内置知识库和规则，未采用独立生产故障集，也未验证真实模型、Java 网关或生产环境的端到端效果；上述结果不代表真实环境准确率。
- 检索指标按去重文档的前 K 个结果中是否包含预期文档计算；工具指标检查预期工具集合是否被调用，根因指标检查输出是否包含任一预期关键词。人工确认拦截率对应 2 条高危样本；默认评测中二次检索触发数为 0，另有单元测试覆盖该分支。
- 当前异常提取、工具选择、Query 改写与重排采用规则和启发式逻辑。同步 RAG 建库与查询使用本地哈希向量；网关 Embeddings 客户端及异步适配器尚未接入主检索链路。
- 对外 SSE 接口输出状态机进度，并将生成后的报告按字符分片发送；上游模型 SSE 解析能力由客户端单独实现与测试。
- 人工确认仅控制报告建议与状态机恢复；工具始终只读。会话检查点保存在内存中；Token 预算包含字符估算，属于流程保护阈值，不是精确计费上限。服务尚未提供认证和租户隔离，建议仅在本地演示。
