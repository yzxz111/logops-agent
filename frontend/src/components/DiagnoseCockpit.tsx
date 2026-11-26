import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  Bot,
  ChevronRight,
  Copy,
  Database,
  ExternalLink,
  FileSearch,
  Play,
  ShieldCheck,
  Sparkles,
  Terminal,
  Wrench,
} from 'lucide-react'
import { confirmHighRisk, fetchSourceFile, streamDiagnose } from '../api'
import type {
  CitationItem,
  DiagnoseResult,
  ExtractedSignals,
  GraphNodeId,
  HighRiskInterrupt,
  NodeTimelineItem,
  NodeVisualStatus,
  PresetScenario,
  SourceFilePayload,
  ToolCallItem,
} from '../types'
import { CitationDrawer } from './CitationDrawer'
import { HumanConfirmModal } from './HumanConfirmModal'
import { LangGraphFlow } from './LangGraphFlow'
import { MarkdownReport } from './MarkdownReport'

const PRESETS: PresetScenario[] = [
  {
    id: 'gateway-504',
    label: '网关 504 上游超时（经典链路）',
    tag: 'RAG + MCP',
    tagTone: 'cyan',
    description: '带 Trace ID 与异常类，完整展示日志切片、源码配置定位与手册溯源。',
    query: 'gateway 网关请求 /api/v1/orders/create 频繁报 HTTP 504 ReadTimeoutException，trace=req-gw-1001',
  },
  {
    id: 'vague-case-32',
    label: '口语化无错误码故障（CASE-32）',
    tag: 'Agentic 改写',
    tagTone: 'violet',
    description: '不含任何英文异常类名或 HTTP 状态码，验证同义改写与混合 RRF 召回。',
    query: '刚做完滚动发版那几分钟接口偶发报错断开，怀疑旧连接被提前关掉',
  },
  {
    id: 'secondary-retry',
    label: '低置信度二次检索回环',
    tag: 'Retry 分支',
    tagTone: 'amber',
    description: '极其模糊的用户反馈，触发 evaluate_relevance -> rewrite_and_retry 自纠错回环。',
    query: '系统感觉突然有点慢，页面偶尔打不开，帮忙初步定位一下',
  },
  {
    id: 'hitl-flushall',
    label: '高危指令 HITL 人工拦截',
    tag: 'Interrupt & Resume',
    tagTone: 'rose',
    description: '包含 FLUSHALL 高危运维意图，演示 LangGraph 中断挂起、弹窗审批与恢复。',
    query: 'Redis 内存报警满了写不进去数据，我想直接执行 FLUSHALL 清空缓存释放内存，请帮我确认方案',
  },
]

const INITIAL_NODE_STATES: Record<GraphNodeId, NodeVisualStatus> = {
  extract_anomaly: 'idle',
  retrieve_and_tools: 'idle',
  evaluate_relevance: 'idle',
  rewrite_and_retry: 'idle',
  high_risk_check: 'idle',
  human_confirm: 'idle',
  generate_report: 'idle',
}

function parseLineRange(lineRange: string): { start: number; end?: number } {
  const m = lineRange.match(/L?(\d+)(?:\s*-\s*L?(\d+))?/i)
  if (!m) return { start: 1 }
  return {
    start: Number(m[1]) || 1,
    end: m[2] ? Number(m[2]) : undefined,
  }
}

interface DiagnoseCockpitProps {
  externalQuery?: string | null
  onConsumedExternalQuery?: () => void
  onRequestIdChange?: (rid: string) => void
}

export const DiagnoseCockpit: React.FC<DiagnoseCockpitProps> = ({
  externalQuery,
  onConsumedExternalQuery,
  onRequestIdChange,
}) => {
  const [query, setQuery] = useState(PRESETS[0].query)
  const [maxSteps, setMaxSteps] = useState(8)
  const [tokenBudget, setTokenBudget] = useState(6000)

  const [running, setRunning] = useState(false)
  const [requestId, setRequestId] = useState('')
  const [threadId, setThreadId] = useState('')
  const [statusText, setStatusText] = useState('就绪')
  const [errorMsg, setErrorMsg] = useState('')

  const [nodeStates, setNodeStates] = useState<Record<GraphNodeId, NodeVisualStatus>>(INITIAL_NODE_STATES)
  const [activeNode, setActiveNode] = useState<GraphNodeId | null>(null)
  const [timeline, setTimeline] = useState<NodeTimelineItem[]>([])

  const [stepCount, setStepCount] = useState(0)
  const [tokenUsed, setTokenUsed] = useState(0)
  const [relevanceScore, setRelevanceScore] = useState<number | null>(null)
  const [retryCount, setRetryCount] = useState(0)
  const [circuitBreakerReason, setCircuitBreakerReason] = useState('')
  const [signals, setSignals] = useState<ExtractedSignals>({})
  const [redactions, setRedactions] = useState<Record<string, number>>({})
  const [rewrittenQueries, setRewrittenQueries] = useState<string[]>([])
  const [citations, setCitations] = useState<CitationItem[]>([])
  const [toolCalls, setToolCalls] = useState<ToolCallItem[]>([])
  const [reportText, setReportText] = useState('')
  const [requiresHumanConfirm, setRequiresHumanConfirm] = useState(false)
  const [humanApproved, setHumanApproved] = useState<boolean | null>(null)

  const [pendingInterrupt, setPendingInterrupt] = useState<HighRiskInterrupt | null>(null)
  const [confirming, setConfirming] = useState(false)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [drawerError, setDrawerError] = useState('')
  const [drawerFile, setDrawerFile] = useState<SourceFilePayload | null>(null)
  const [drawerTitleHint, setDrawerTitleHint] = useState('')
  const [copied, setCopied] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const reportRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (externalQuery) {
      setQuery(externalQuery)
      onConsumedExternalQuery?.()
    }
  }, [externalQuery, onConsumedExternalQuery])

  useEffect(() => {
    if (reportRef.current && running) {
      reportRef.current.scrollTop = reportRef.current.scrollHeight
    }
  }, [reportText, running])

  const compressionText = useMemo(() => {
    let raw = 0
    let comp = 0
    for (const t of toolCalls) {
      raw += t.raw_chars || 0
      comp += t.compressed_chars || 0
    }
    if (!raw) return '--'
    const pct = Math.max(0, Math.round((1 - comp / raw) * 1000) / 10)
    return `${pct}% (${raw}→${comp})`
  }, [toolCalls])

  const resetRunState = () => {
    setNodeStates({ ...INITIAL_NODE_STATES })
    setActiveNode('extract_anomaly')
    setTimeline([])
    setStepCount(0)
    setTokenUsed(0)
    setRelevanceScore(null)
    setRetryCount(0)
    setCircuitBreakerReason('')
    setSignals({})
    setRedactions({})
    setRewrittenQueries([])
    setCitations([])
    setToolCalls([])
    setReportText('')
    setRequiresHumanConfirm(false)
    setHumanApproved(null)
    setPendingInterrupt(null)
    setErrorMsg('')
  }

  const openSourceLocation = async (path: string, startLine = 1, endLine?: number, hint?: string) => {
    setDrawerOpen(true)
    setDrawerLoading(true)
    setDrawerError('')
    setDrawerFile(null)
    setDrawerTitleHint(hint || path)
    try {
      const payload = await fetchSourceFile(path, startLine, endLine)
      setDrawerFile(payload)
    } catch (err) {
      setDrawerError(err instanceof Error ? err.message : '加载溯源内容失败')
    } finally {
      setDrawerLoading(false)
    }
  }

  const handleStartDiagnosis = async (overrideQuery?: string) => {
    const targetQuery = (overrideQuery ?? query).trim()
    if (targetQuery.length < 2) {
      setErrorMsg('请输入至少 2 个字符的故障描述或异常堆栈')
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const rid = `ui-${Date.now().toString(36)}`
    setRequestId(rid)
    onRequestIdChange?.(rid)
    resetRunState()
    setRunning(true)
    setStatusText('SSE 流式排障执行中...')

    try {
      await streamDiagnose(
        {
          query: targetQuery,
          requestId: rid,
          maxSteps,
          tokenBudget,
          signal: controller.signal,
        },
        {
          onStart: (data) => {
            setThreadId(data.thread_id)
            setRequestId(data.request_id || rid)
            onRequestIdChange?.(data.request_id || rid)
          },
          onNodeUpdate: (data) => {
            const node = data.node as GraphNodeId
            if (typeof data.step_count === 'number') setStepCount(data.step_count)
            if (typeof data.token_used === 'number') setTokenUsed(data.token_used)
            if (data.circuit_breaker_reason) setCircuitBreakerReason(data.circuit_breaker_reason)
            if (data.extracted_signals) setSignals(data.extracted_signals as ExtractedSignals)
            if (data.redaction_counts) setRedactions(data.redaction_counts)
            if (data.rewritten_queries) setRewrittenQueries(data.rewritten_queries)
            if (data.rag_citations) setCitations(data.rag_citations)
            if (data.tool_calls) setToolCalls(data.tool_calls)
            if (typeof data.relevance_score === 'number') setRelevanceScore(data.relevance_score)
            if (typeof data.retry_count === 'number') setRetryCount(data.retry_count)
            if (typeof data.requires_human_confirm === 'boolean') {
              setRequiresHumanConfirm(data.requires_human_confirm)
            }

            setNodeStates((prev) => {
              const next = { ...prev }
              if (node === 'rewrite_and_retry') {
                next.rewrite_and_retry = 'retried'
              } else {
                next[node] = 'completed'
              }
              return next
            })

            const nextGuess: Partial<Record<GraphNodeId, GraphNodeId>> = {
              extract_anomaly: 'retrieve_and_tools',
              retrieve_and_tools: 'evaluate_relevance',
              evaluate_relevance:
                data.is_relevant === false ? 'rewrite_and_retry' : 'high_risk_check',
              rewrite_and_retry: 'evaluate_relevance',
              high_risk_check: data.requires_human_confirm ? 'human_confirm' : 'generate_report',
              human_confirm: 'generate_report',
            }
            setActiveNode(nextGuess[node] ?? null)

            let detail = `step=${data.step_count ?? '-'}`
            if (node === 'extract_anomaly' && data.extracted_signals) {
              const svc = (data.extracted_signals as ExtractedSignals).service || '待识别'
              detail = `服务=${svc}`
            } else if (node === 'retrieve_and_tools') {
              detail = `检索=${data.rag_citations?.length ?? 0}条 / 工具=${data.tool_calls?.length ?? 0}次`
            } else if (node === 'evaluate_relevance') {
              detail = `相关度=${data.relevance_score ?? '-'} (${data.is_relevant ? '通过' : '触发重检'})`
            } else if (node === 'rewrite_and_retry') {
              detail = `扩展重检第 ${data.retry_count ?? 1} 次`
            } else if (node === 'high_risk_check') {
              detail = data.requires_human_confirm ? '命中高危操作 -> 挂起' : '安全放行'
            }

            setTimeline((prev) => [
              ...prev,
              {
                step: data.step_count || prev.length + 1,
                node,
                detail,
                timestamp: new Date().toLocaleTimeString(),
              },
            ])
          },
          onHumanConfirmRequired: (payload) => {
            setRunning(false)
            setActiveNode('human_confirm')
            setRequiresHumanConfirm(true)
            setStatusText('等待人工审批确认（HITL 中断）')
            setNodeStates((prev) => ({
              ...prev,
              human_confirm: 'interrupted',
            }))
            if (payload.snapshot) {
              const s = payload.snapshot
              if (s.rag_citations) setCitations(s.rag_citations)
              if (s.tool_calls) setToolCalls(s.tool_calls)
              if (s.rewritten_queries) setRewrittenQueries(s.rewritten_queries)
              if (typeof s.step_count === 'number') setStepCount(s.step_count)
              if (typeof s.token_used === 'number') setTokenUsed(s.token_used)
              if (typeof s.relevance_score === 'number') setRelevanceScore(s.relevance_score)
            }
            setPendingInterrupt(payload)
          },
          onToken: (tok) => {
            setReportText((prev) => prev + tok.delta)
          },
          onDone: (summary: DiagnoseResult) => {
            setRunning(false)
            setActiveNode(null)
            setStepCount(summary.step_count)
            setTokenUsed(summary.token_used)
            setRelevanceScore(summary.relevance_score)
            setRetryCount(summary.retry_count)
            setCircuitBreakerReason(summary.circuit_breaker_reason || '')
            setRewrittenQueries(summary.rewritten_queries || [])
            setCitations(summary.rag_citations || [])
            setToolCalls(summary.tool_calls || [])
            setRedactions(summary.redaction_counts || {})
            if (summary.final_report) setReportText(summary.final_report)
            setStatusText(summary.status === 'circuit_broken' ? '触发熔断保护降级输出' : '诊断完成')
            setNodeStates((prev) => ({
              ...prev,
              rewrite_and_retry: summary.retry_count > 0 ? 'retried' : 'skipped',
              human_confirm: summary.requires_human_confirm ? prev.human_confirm : 'skipped',
              generate_report: 'completed',
            }))
          },
        },
      )
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setErrorMsg(err instanceof Error ? err.message : '诊断执行异常')
        setStatusText('执行失败')
      }
      setRunning(false)
      setActiveNode(null)
    }
  }

  const handleConfirmDecision = async (approved: boolean, comment: string) => {
    if (!pendingInterrupt) return
    setConfirming(true)
    setErrorMsg('')
    try {
      const result = await confirmHighRisk(
        pendingInterrupt.thread_id,
        approved,
        comment,
        requestId || pendingInterrupt.request_id,
      )
      setPendingInterrupt(null)
      setHumanApproved(approved)
      setNodeStates((prev) => ({
        ...prev,
        human_confirm: 'completed',
        generate_report: 'completed',
      }))
      setActiveNode(null)
      setStepCount(result.step_count)
      setTokenUsed(result.token_used)
      setCitations(result.rag_citations || [])
      setToolCalls(result.tool_calls || [])
      setReportText(result.final_report)
      setStatusText(approved ? '人工已批准恢复并生成报告' : '已拒绝高危指令并降级只读建议')
      setTimeline((prev) => [
        ...prev,
        {
          step: result.step_count - 1,
          node: 'human_confirm',
          detail: approved ? '人工批准继续' : '人工拒绝 · 降级建议',
          timestamp: new Date().toLocaleTimeString(),
        },
        {
          step: result.step_count,
          node: 'generate_report',
          detail: '恢复生成最终报告',
          timestamp: new Date().toLocaleTimeString(),
        },
      ])
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : '人工确认恢复失败')
    } finally {
      setConfirming(false)
    }
  }

  const handleCopyReport = async () => {
    if (!reportText) return
    await navigator.clipboard.writeText(reportText)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className="cockpit-grid">
      {/* Left Column: Input & Scenarios */}
      <aside className="section-stack">
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Terminal size={15} color="#38bdf8" />
              故障描述 / 异常堆栈输入
            </div>
            <span className="tag tag-cyan">SSE 流式</span>
          </div>

          <textarea
            className="query-textarea"
            data-testid="query-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault()
                void handleStartDiagnosis()
              }
            }}
            placeholder="输入线上告警、口语化现象描述或脱敏前的异常堆栈..."
          />

          <div className="control-grid">
            <div className="control-box">
              <div className="control-label">
                <span>最大步数 (max_steps)</span>
                <strong>{maxSteps}</strong>
              </div>
              <input
                type="range"
                min={2}
                max={12}
                value={maxSteps}
                onChange={(e) => setMaxSteps(Number(e.target.value))}
              />
            </div>
            <div className="control-box">
              <div className="control-label">
                <span>Token 预算</span>
                <strong>{tokenBudget}</strong>
              </div>
              <input
                type="range"
                min={500}
                max={20000}
                step={500}
                value={tokenBudget}
                onChange={(e) => setTokenBudget(Number(e.target.value))}
              />
            </div>
          </div>

          {errorMsg ? (
            <div
              style={{
                marginTop: 10,
                padding: '8px 10px',
                borderRadius: 8,
                background: 'rgba(244, 63, 94, 0.14)',
                border: '1px solid rgba(244, 63, 94, 0.3)',
                color: '#fecdd3',
                fontSize: 12,
              }}
            >
              {errorMsg}
            </div>
          ) : null}

          <button
            type="button"
            className="btn-primary"
            style={{ marginTop: 12 }}
            disabled={running}
            onClick={() => void handleStartDiagnosis()}
            data-testid="start-diagnose-btn"
          >
            <Play size={15} />
            {running ? '正在推演 LangGraph 节点...' : '开始智能排障 (Ctrl + Enter)'}
          </button>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Sparkles size={15} color="#a78bfa" />
              典型演练场景（一键带入）
            </div>
          </div>
          <div className="preset-list">
            {PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className="preset-card"
                data-testid={`preset-${preset.id}`}
                onClick={() => {
                  setQuery(preset.query)
                  void handleStartDiagnosis(preset.query)
                }}
              >
                <div className="preset-top">
                  <span className="preset-title">{preset.label}</span>
                  <span className={`tag tag-${preset.tagTone}`}>{preset.tag}</span>
                </div>
                <div className="preset-desc">{preset.description}</div>
              </button>
            ))}
          </div>
        </section>
      </aside>

      {/* Center Column: LangGraph Flow + Telemetry + Streaming Report */}
      <main className="section-stack">
        <div className="metrics-row">
          <div className="metric-chip">
            <div className="metric-label">执行状态</div>
            <div className="metric-value" style={{ fontSize: 13 }} data-testid="status-text">
              {statusText}
            </div>
          </div>
          <div className="metric-chip">
            <div className="metric-label">步数 / 熔断上限</div>
            <div className="metric-value">
              {stepCount} / {maxSteps}
            </div>
          </div>
          <div className="metric-chip">
            <div className="metric-label">Token 估算 / 预算</div>
            <div className="metric-value">
              {tokenUsed} / {tokenBudget}
            </div>
          </div>
          <div className="metric-chip">
            <div className="metric-label">相关性 / 二次检索</div>
            <div className="metric-value">
              {relevanceScore !== null ? relevanceScore.toFixed(2) : '--'} · retry={retryCount}
            </div>
          </div>
        </div>

        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Activity size={15} color="#38bdf8" />
              LangGraph 实时状态机流转图
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11.5, color: '#94a3b8' }}>
              {signals.service ? <span className="tag tag-cyan">服务: {signals.service}</span> : null}
              {threadId ? <span className="pill pill-mono">thread: {threadId.slice(0, 8)}</span> : null}
            </div>
          </div>

          <LangGraphFlow
            nodeStates={nodeStates}
            activeNode={activeNode}
            relevanceScore={relevanceScore}
            retryCount={retryCount}
            requiresHumanConfirm={requiresHumanConfirm}
            humanApproved={humanApproved}
            circuitBreakerReason={circuitBreakerReason}
          />

          {timeline.length > 0 ? (
            <div className="timeline-strip">
              {timeline.map((item, idx) => (
                <div key={`${item.node}-${idx}`} className="timeline-badge">
                  <strong style={{ color: '#38bdf8' }}>#{item.step}</strong>
                  <span style={{ fontFamily: 'var(--font-mono)', color: '#e2e8f0' }}>{item.node}</span>
                  <span>{item.detail}</span>
                </div>
              ))}
            </div>
          ) : null}
        </section>

        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Bot size={15} color="#10b981" />
              SSE 实时根因诊断报告
            </div>
            <button
              type="button"
              className="btn-secondary"
              disabled={!reportText}
              onClick={() => void handleCopyReport()}
            >
              <Copy size={13} />
              {copied ? '已复制' : '复制报告'}
            </button>
          </div>
          <div className="report-box" ref={reportRef} data-testid="streaming-report">
            <MarkdownReport content={reportText} />
          </div>
        </section>
      </main>

      {/* Right Column: Rewrites, MCP Tools & Clickable Citations */}
      <aside className="section-stack cockpit-right">
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <ShieldCheck size={15} color="#10b981" />
              信号提取与脱敏审计
            </div>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, fontSize: 12 }}>
            <span className="pill">服务: {signals.service || '自动推断中'}</span>
            {signals.trace_id ? <span className="pill pill-mono">trace: {signals.trace_id}</span> : null}
            {(signals.error_codes || []).map((code) => (
              <span key={code} className="tag tag-amber">
                code: {code}
              </span>
            ))}
            {(signals.exception_classes || []).map((exc) => (
              <span key={exc} className="tag tag-rose">
                {exc}
              </span>
            ))}
            {Object.keys(redactions).length > 0 ? (
              Object.entries(redactions).map(([k, v]) => (
                <span key={k} className="tag tag-emerald">
                  已脱敏 {k}: {v}
                </span>
              ))
            ) : (
              <span className="pill">无明文敏感字段</span>
            )}
          </div>

          {rewrittenQueries.length > 0 ? (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11.5, color: '#94a3b8', marginBottom: 6 }}>
                Agentic Query 语义改写扩展（{rewrittenQueries.length} 路检索）
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {rewrittenQueries.map((rq, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: '6px 9px',
                      borderRadius: 7,
                      background: 'var(--bg-input)',
                      border: '1px solid var(--border-subtle)',
                      fontSize: 11.5,
                      fontFamily: 'var(--font-mono)',
                      color: '#cbd5e1',
                    }}
                  >
                    Q{idx + 1}: {rq}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </section>

        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Wrench size={15} color="#f59e0b" />
              只读 MCP 取证证据
            </div>
            <span style={{ fontSize: 11, color: '#94a3b8' }}>压缩率: {compressionText}</span>
          </div>

          {toolCalls.length === 0 ? (
            <div style={{ fontSize: 12, color: '#64748b' }}>暂无工具调用记录</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {toolCalls.map((tc, idx) => (
                <div
                  key={`${tc.tool}-${idx}`}
                  style={{
                    padding: '10px 11px',
                    borderRadius: 10,
                    background: 'rgba(18, 27, 48, 0.55)',
                    border: '1px solid var(--border-subtle)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <code style={{ color: '#fcd34d', fontSize: 12 }}>{tc.tool}</code>
                    <span className="tag tag-emerald">命中 {tc.total_matches} 条</span>
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: '#94a3b8',
                      marginTop: 4,
                      fontFamily: 'var(--font-mono)',
                      wordBreak: 'break-all',
                    }}
                  >
                    {JSON.stringify(tc.args)}
                  </div>
                  {tc.locations && tc.locations.length > 0 ? (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                      {tc.locations.map((loc, lIdx) => (
                        <button
                          key={lIdx}
                          type="button"
                          className="loc-link"
                          onClick={() =>
                            void openSourceLocation(
                              loc.path,
                              loc.start_line,
                              loc.end_line,
                              `${loc.path}#L${loc.start_line}-L${loc.end_line}`,
                            )
                          }
                        >
                          <FileSearch size={12} />
                          {loc.path.replace(/^data\//, '')}#L{loc.start_line}-L{loc.end_line}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Database size={15} color="#38bdf8" />
              知识库 Citation 溯源（点击查看高亮原文）
            </div>
            <span className="tag tag-cyan">{citations.length} 条</span>
          </div>

          {citations.length === 0 ? (
            <div style={{ fontSize: 12, color: '#64748b' }}>检索完成后将显示可点击的溯源引用卡片</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }} data-testid="citation-list">
              {citations.map((c, idx) => {
                const range = parseLineRange(c.line_range)
                return (
                  <button
                    key={c.chunk_id}
                    type="button"
                    className="citation-card"
                    data-testid={`citation-card-${idx}`}
                    onClick={() =>
                      void openSourceLocation(
                        c.source_path,
                        range.start,
                        range.end,
                        `[${c.doc_id}] ${c.title}`,
                      )
                    }
                  >
                    <div className="citation-meta">
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <span className="tag tag-cyan">{c.doc_id}</span>
                        <span className="tag tag-violet">{c.service}</span>
                        {c.error_code ? <span className="tag tag-amber">{c.error_code}</span> : null}
                      </div>
                      <span style={{ fontFamily: 'var(--font-mono)', color: '#6ee7b7' }}>
                        score {c.score.toFixed(2)}
                      </span>
                    </div>
                    <div style={{ fontWeight: 600, fontSize: 12.5, color: '#f1f5f9' }}>{c.title}</div>
                    <div className="citation-snippet">{c.snippet}</div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginTop: 8,
                        fontSize: 11,
                        color: '#7dd3fc',
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      <span>
                        {c.source_path}#{c.line_range}
                      </span>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                        打开高亮抽屉 <ChevronRight size={13} /> <ExternalLink size={11} />
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </section>
      </aside>

      <CitationDrawer
        open={drawerOpen}
        loading={drawerLoading}
        error={drawerError}
        fileData={drawerFile}
        titleHint={drawerTitleHint}
        onClose={() => setDrawerOpen(false)}
      />

      <HumanConfirmModal
        interrupt={pendingInterrupt}
        submitting={confirming}
        onConfirm={(approved, comment) => void handleConfirmDecision(approved, comment)}
      />
    </div>
  )
}
