import React, { useEffect, useMemo, useState } from 'react'
import { BarChart3, FlaskConical, Play, RefreshCw, Search } from 'lucide-react'
import { fetchEvalReport, rerunEvalReport, searchRag } from '../api'
import type { EvalReportPayload, RagSearchResponse, SearchMode } from '../types'

const MODES: Array<{ key: SearchMode; label: string; color: string }> = [
  { key: 'bm25_only', label: 'BM25 Only', color: '#64748b' },
  { key: 'vector_only', label: 'Vector Only', color: '#a78bfa' },
  { key: 'hybrid_rrf', label: 'Hybrid RRF', color: '#3b82f6' },
  { key: 'agentic', label: 'Agentic (改写+RRF+重排)', color: '#10b981' },
]

const METRIC_KEYS: Array<keyof EvalReportPayload['rag_comparison']['agentic']> = [
  'Recall@1',
  'Recall@3',
  'Recall@5',
  'MRR',
]

interface EvalDashboardProps {
  onReplayInCockpit: (query: string) => void
}

export const EvalDashboard: React.FC<EvalDashboardProps> = ({ onReplayInCockpit }) => {
  const [report, setReport] = useState<EvalReportPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [rerunning, setRerunning] = useState(false)
  const [error, setError] = useState('')
  const [difficultyFilter, setDifficultyFilter] = useState<'all' | 'easy' | 'medium' | 'hard'>('all')

  const [labQuery, setLabQuery] = useState(
    '用户登录校验不通过，疑似签名不对或者令牌已经过有效期被拦截',
  )
  const [labLoading, setLabLoading] = useState(false)
  const [labResults, setLabResults] = useState<{
    bm25?: RagSearchResponse
    vector?: RagSearchResponse
    agentic?: RagSearchResponse
  }>({})

  const loadReport = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchEvalReport()
      setReport(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载评测数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadReport()
    void runLabComparison('用户登录校验不通过，疑似签名不对或者令牌已经过有效期被拦截')
  }, [])

  const handleRerun = async () => {
    setRerunning(true)
    setError('')
    try {
      const data = await rerunEvalReport()
      setReport(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : '重跑评测失败')
    } finally {
      setRerunning(false)
    }
  }

  const runLabComparison = async (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return
    setLabLoading(true)
    try {
      const [bm25, vector, agentic] = await Promise.all([
        searchRag(trimmed, 'bm25_only', 3),
        searchRag(trimmed, 'vector_only', 3),
        searchRag(trimmed, 'agentic', 3),
      ])
      setLabResults({ bm25, vector, agentic })
    } finally {
      setLabLoading(false)
    }
  }

  const filteredCases = useMemo(() => {
    if (!report) return []
    if (difficultyFilter === 'all') return report.case_details
    return report.case_details.filter((c) => c.difficulty === difficultyFilter)
  }, [report, difficultyFilter])

  if (loading) {
    return (
      <div className="eval-container">
        <div className="panel">正在加载 40 条故障评测报告...</div>
      </div>
    )
  }

  if (error || !report) {
    return (
      <div className="eval-container">
        <div className="panel" style={{ color: '#fda4af' }}>
          {error || '未能加载评测数据'}
        </div>
      </div>
    )
  }

  const bm25R1 = report.rag_comparison.bm25_only?.['Recall@1'] ?? 0
  const agenticR1 = report.rag_comparison.agentic?.['Recall@1'] ?? 0
  const r1Gain = ((agenticR1 - bm25R1) * 100).toFixed(2)

  return (
    <div className="eval-container" data-testid="eval-dashboard">
      {/* KPI Overview */}
      <div className="kpi-grid">
        <div className="panel">
          <div className="metric-label">评测样本 / 知识分块</div>
          <div className="metric-value" style={{ fontSize: 22, marginTop: 4 }}>
            {report.total_cases} 条 / {report.indexed_chunks} 块
          </div>
          <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 4 }}>
            含 15 条 hard 口语化模糊/高危样本
          </div>
        </div>
        <div className="panel">
          <div className="metric-label">Agentic Recall@1 / MRR</div>
          <div className="metric-value" style={{ fontSize: 22, marginTop: 4, color: '#10b981' }}>
            {(agenticR1 * 100).toFixed(2)}% / {report.rag_comparison.agentic.MRR.toFixed(4)}
          </div>
          <div style={{ fontSize: 11.5, color: '#6ee7b7', marginTop: 4 }}>
            相比 BM25 Recall@1 提升 +{r1Gain}%
          </div>
        </div>
        <div className="panel">
          <div className="metric-label">工具调用 / 根因命中率</div>
          <div className="metric-value" style={{ fontSize: 22, marginTop: 4 }}>
            {(report.agent_metrics.tool_accuracy * 100).toFixed(0)}% /{' '}
            {(report.agent_metrics.root_cause_hit_rate * 100).toFixed(0)}%
          </div>
          <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 4 }}>只读 MCP 日志 + 源码定位</div>
        </div>
        <div className="panel">
          <div className="metric-label">高危人工确认拦截率</div>
          <div className="metric-value" style={{ fontSize: 22, marginTop: 4, color: '#fda4af' }}>
            {(report.agent_metrics.high_risk_interception_rate * 100).toFixed(0)}%
          </div>
          <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 4 }}>LangGraph Interrupt 拦截</div>
        </div>
        <div className="panel">
          <div className="metric-label">工具上下文压缩率</div>
          <div className="metric-value" style={{ fontSize: 22, marginTop: 4, color: '#7dd3fc' }}>
            {(report.agent_metrics.tool_context_compression_ratio * 100).toFixed(2)}%
          </div>
          <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 4 }}>脱敏 + 错误窗口提取</div>
        </div>
      </div>

      <div className="eval-split">
        {/* Grouped Bar Chart + Comparison Table */}
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <BarChart3 size={16} color="#38bdf8" />
              BM25 vs Vector vs Hybrid RRF vs Agentic 召回对比
            </div>
            <button
              type="button"
              className="btn-secondary"
              disabled={rerunning}
              onClick={() => void handleRerun()}
            >
              <RefreshCw size={13} />
              {rerunning ? '评测运行中...' : '现场重跑 40 条评测'}
            </button>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 10 }}>
            {MODES.map((m) => (
              <div key={m.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 3,
                    background: m.color,
                    display: 'inline-block',
                  }}
                />
                <span style={{ color: '#cbd5e1' }}>{m.label}</span>
              </div>
            ))}
          </div>

          <svg viewBox="0 0 640 230" style={{ width: '100%', height: 'auto', display: 'block' }}>
            {[0.7, 0.8, 0.9, 1.0].map((tick) => {
              const y = 190 - ((tick - 0.65) / 0.35) * 160
              return (
                <g key={tick}>
                  <line x1="48" y1={y} x2="620" y2={y} stroke="rgba(148,163,184,0.14)" strokeDasharray="3 3" />
                  <text x="40" y={y + 4} textAnchor="end" fill="#64748b" fontSize="10.5">
                    {Math.round(tick * 100)}%
                  </text>
                </g>
              )
            })}

            {METRIC_KEYS.map((metric, groupIdx) => {
              const groupX = 76 + groupIdx * 138
              return (
                <g key={metric}>
                  {MODES.map((m, barIdx) => {
                    const val = report.rag_comparison[m.key]?.[metric] ?? 0
                    const clamped = Math.max(0.65, Math.min(1.0, val))
                    const barHeight = ((clamped - 0.65) / 0.35) * 160
                    const x = groupX + barIdx * 24
                    const y = 190 - barHeight
                    return (
                      <g key={m.key}>
                        <rect x={x} y={y} width="19" height={Math.max(4, barHeight)} rx="4" fill={m.color} />
                        <text
                          x={x + 9.5}
                          y={y - 5}
                          textAnchor="middle"
                          fill="#cbd5e1"
                          fontSize="9"
                          fontFamily="var(--font-mono)"
                        >
                          {(val * 100).toFixed(0)}
                        </text>
                      </g>
                    )
                  })}
                  <text x={groupX + 42} y="214" textAnchor="middle" fill="#cbd5e1" fontSize="11.5" fontWeight="600">
                    {metric}
                  </text>
                </g>
              )
            })}
          </svg>

          <table className="data-table" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>检索模式</th>
                <th>Recall@1</th>
                <th>Recall@3</th>
                <th>Recall@5</th>
                <th>MRR</th>
              </tr>
            </thead>
            <tbody>
              {MODES.map((m) => {
                const row = report.rag_comparison[m.key]
                return (
                  <tr key={m.key}>
                    <td>
                      <strong style={{ color: m.key === 'agentic' ? '#6ee7b7' : '#e2e8f0' }}>{m.label}</strong>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{(row['Recall@1'] * 100).toFixed(2)}%</td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{(row['Recall@3'] * 100).toFixed(2)}%</td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{(row['Recall@5'] * 100).toFixed(2)}%</td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{row.MRR.toFixed(4)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>

        {/* Interactive RAG Mode Lab */}
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <FlaskConical size={16} color="#a78bfa" />
              在线 RAG 检索模式实时对比实验室
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <input
              type="text"
              value={labQuery}
              onChange={(e) => setLabQuery(e.target.value)}
              placeholder="输入口语化无错误码故障描述..."
              style={{
                flex: 1,
                padding: '9px 12px',
                borderRadius: 9,
                border: '1px solid var(--border-subtle)',
                background: 'var(--bg-input)',
                color: '#f1f5f9',
                fontSize: 12.5,
              }}
            />
            <button
              type="button"
              className="btn-secondary"
              disabled={labLoading}
              onClick={() => void runLabComparison(labQuery)}
            >
              <Search size={14} />
              {labLoading ? '对比中' : '现场对比'}
            </button>
          </div>

          {labResults.agentic?.rewritten_queries ? (
            <div style={{ marginTop: 10, fontSize: 11.5, color: '#94a3b8' }}>
              <div>QueryRewriter 语义扩展：</div>
              {labResults.agentic.rewritten_queries.map((rq, idx) => (
                <div
                  key={idx}
                  style={{
                    marginTop: 4,
                    padding: '4px 8px',
                    borderRadius: 6,
                    background: 'var(--bg-input)',
                    fontFamily: 'var(--font-mono)',
                    color: '#bae6fd',
                  }}
                >
                  {idx + 1}. {rq}
                </div>
              ))}
            </div>
          ) : null}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 12 }}>
            {[
              { title: 'BM25 Only (基线)', res: labResults.bm25, badge: 'tag-amber' },
              { title: 'Agentic RRF + 重排', res: labResults.agentic, badge: 'tag-emerald' },
            ].map((col) => (
              <div
                key={col.title}
                style={{
                  padding: 10,
                  borderRadius: 10,
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <strong style={{ fontSize: 12 }}>{col.title}</strong>
                  <span className={`tag ${col.badge}`}>Top-3</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(col.res?.citations || []).map((c, idx) => (
                    <div
                      key={`${c.chunk_id}-${idx}`}
                      style={{
                        padding: '6px 8px',
                        borderRadius: 7,
                        background: 'rgba(18, 27, 48, 0.7)',
                        fontSize: 11.5,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <strong style={{ color: '#7dd3fc' }}>
                          #{idx + 1} {c.doc_id}
                        </strong>
                        <span style={{ fontFamily: 'var(--font-mono)', color: '#94a3b8' }}>
                          {c.score.toFixed(3)}
                        </span>
                      </div>
                      <div style={{ color: '#cbd5e1', marginTop: 2 }}>{c.title}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Case Breakdown Table */}
      <section className="panel">
        <div className="panel-header">
          <div className="panel-title">40 条故障评测明细（支持点击一键回放到驾驶舱）</div>
          <div style={{ display: 'flex', gap: 6 }}>
            {(['all', 'hard', 'medium', 'easy'] as const).map((diff) => (
              <button
                key={diff}
                type="button"
                className="btn-secondary"
                style={{
                  borderColor: difficultyFilter === diff ? '#38bdf8' : undefined,
                  color: difficultyFilter === diff ? '#38bdf8' : undefined,
                }}
                onClick={() => setDifficultyFilter(diff)}
              >
                {diff === 'all' ? '全部' : diff}
              </button>
            ))}
          </div>
        </div>

        <div style={{ overflowX: 'auto', maxHeight: 420 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>难度</th>
                <th>故障输入描述</th>
                <th>预期文档</th>
                <th>Top-1 命中</th>
                <th>MCP 工具</th>
                <th>步数 / Token</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredCases.map((c) => (
                <tr key={c.id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{c.id}</td>
                  <td>
                    <span
                      className={`tag ${
                        c.difficulty === 'hard'
                          ? 'tag-rose'
                          : c.difficulty === 'medium'
                            ? 'tag-amber'
                            : 'tag-cyan'
                      }`}
                    >
                      {c.difficulty}
                    </span>
                  </td>
                  <td style={{ maxWidth: 420 }}>{c.query}</td>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>{c.expected_doc_ids.join(', ')}</td>
                  <td>
                    <span
                      className={`tag ${
                        c.top_doc && c.expected_doc_ids.includes(c.top_doc) ? 'tag-emerald' : 'tag-rose'
                      }`}
                    >
                      {c.top_doc || '--'}
                    </span>
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{c.tools.join(', ')}</td>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>
                    {c.steps} / {c.tokens}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => onReplayInCockpit(c.query)}
                    >
                      <Play size={12} />
                      演示
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
