import React, { useEffect, useState } from 'react'
import { BarChart3, Cpu, Terminal } from 'lucide-react'
import { fetchHealth } from './api'
import { DiagnoseCockpit } from './components/DiagnoseCockpit'
import { EvalDashboard } from './components/EvalDashboard'
import type { HealthInfo } from './types'

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'cockpit' | 'eval'>('cockpit')
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [latestRequestId, setLatestRequestId] = useState('')
  const [replayQuery, setReplayQuery] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const info = await fetchHealth('ui-boot-health')
        setHealth(info)
        setHealthError(false)
        setLatestRequestId(info.request_id)
      } catch {
        setHealthError(true)
      }
    }
    void load()
  }, [])

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-icon">
            <Cpu size={19} />
          </div>
          <div>
            <div className="brand-title">LogOps-Agent 智能排障驾驶舱</div>
            <div className="brand-sub">
              LangGraph 状态机 · Hybrid RAG (BM25 + Qdrant RRF) · ReadOnly MCP · HITL 安全审批
            </div>
          </div>
        </div>

        <nav className="nav-tabs" aria-label="主视图切换">
          <button
            type="button"
            className={`nav-tab ${activeTab === 'cockpit' ? 'active' : ''}`}
            onClick={() => setActiveTab('cockpit')}
            data-testid="tab-cockpit"
          >
            <Terminal size={15} />
            实时排障驾驶舱
          </button>
          <button
            type="button"
            className={`nav-tab ${activeTab === 'eval' ? 'active' : ''}`}
            onClick={() => setActiveTab('eval')}
            data-testid="tab-eval"
          >
            <BarChart3 size={15} />
            RAG 对比与 40 条评测看板
          </button>
        </nav>

        <div className="status-strip">
          <span className="pill" data-testid="health-badge">
            <span className={`dot ${healthError ? 'dot-err' : 'dot-ok'}`} />
            {healthError
              ? '后端离线'
              : health
                ? `在线 · ${health.llm_provider.toUpperCase()} · ${health.indexed_chunks} chunks`
                : '连接中...'}
          </span>
          {latestRequestId ? (
            <span className="pill pill-mono" title="X-Request-ID 透传追踪">
              X-Request-ID: {latestRequestId}
            </span>
          ) : null}
        </div>
      </header>

      {activeTab === 'cockpit' ? (
        <DiagnoseCockpit
          externalQuery={replayQuery}
          onConsumedExternalQuery={() => setReplayQuery(null)}
          onRequestIdChange={setLatestRequestId}
        />
      ) : (
        <EvalDashboard
          onReplayInCockpit={(q) => {
            setReplayQuery(q)
            setActiveTab('cockpit')
          }}
        />
      )}
    </div>
  )
}

export default App
