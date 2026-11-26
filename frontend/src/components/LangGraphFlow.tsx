import React from 'react'
import type { GraphNodeId, NodeVisualStatus } from '../types'

interface LangGraphFlowProps {
  nodeStates: Record<GraphNodeId, NodeVisualStatus>
  activeNode: GraphNodeId | null
  relevanceScore: number | null
  retryCount: number
  requiresHumanConfirm: boolean
  humanApproved: boolean | null
  circuitBreakerReason: string
}

interface NodeMeta {
  id: GraphNodeId
  label: string
  sub: string
  x: number
  y: number
}

const NODES: NodeMeta[] = [
  { id: 'extract_anomaly', label: 'extract_anomaly', sub: '脱敏 · 信号提取', x: 110, y: 110 },
  { id: 'retrieve_and_tools', label: 'retrieve_and_tools', sub: 'Hybrid RAG + MCP', x: 300, y: 110 },
  { id: 'evaluate_relevance', label: 'evaluate_relevance', sub: '相关性评估', x: 495, y: 110 },
  { id: 'rewrite_and_retry', label: 'rewrite_and_retry', sub: 'Query 扩展二次检索', x: 495, y: 230 },
  { id: 'high_risk_check', label: 'high_risk_check', sub: '高危操作审计', x: 690, y: 110 },
  { id: 'human_confirm', label: 'human_confirm', sub: 'HITL 中断与恢复', x: 690, y: 230 },
  { id: 'generate_report', label: 'generate_report', sub: '根因报告流式生成', x: 890, y: 110 },
]

function getStyle(status: NodeVisualStatus, isActive: boolean) {
  if (status === 'interrupted') {
    return {
      fill: 'rgba(244, 63, 94, 0.16)',
      stroke: '#f43f5e',
      text: '#fecdd3',
      badge: '等待审批',
    }
  }
  if (isActive || status === 'active') {
    return {
      fill: 'rgba(56, 189, 248, 0.18)',
      stroke: '#38bdf8',
      text: '#e0f2fe',
      badge: '执行中',
    }
  }
  if (status === 'retried') {
    return {
      fill: 'rgba(245, 158, 11, 0.16)',
      stroke: '#f59e0b',
      text: '#fde68a',
      badge: '已触发',
    }
  }
  if (status === 'completed') {
    return {
      fill: 'rgba(16, 185, 129, 0.14)',
      stroke: '#10b981',
      text: '#d1fae5',
      badge: '已完成',
    }
  }
  if (status === 'skipped') {
    return {
      fill: 'rgba(30, 41, 59, 0.35)',
      stroke: 'rgba(148, 163, 184, 0.2)',
      text: '#64748b',
      badge: '跳过',
    }
  }
  return {
    fill: 'rgba(15, 23, 42, 0.78)',
    stroke: 'rgba(148, 163, 184, 0.28)',
    text: '#cbd5e1',
    badge: '待执行',
  }
}

export const LangGraphFlow: React.FC<LangGraphFlowProps> = ({
  nodeStates,
  activeNode,
  relevanceScore,
  retryCount,
  requiresHumanConfirm,
  humanApproved,
  circuitBreakerReason,
}) => {
  const edgeColor = (active: boolean, warn = false) => {
    if (warn && active) return '#f59e0b'
    return active ? '#38bdf8' : 'rgba(148, 163, 184, 0.28)'
  }

  const retryTaken = retryCount > 0 || nodeStates.rewrite_and_retry === 'completed' || nodeStates.rewrite_and_retry === 'active'
  const hitlTaken = requiresHumanConfirm || nodeStates.human_confirm !== 'idle' && nodeStates.human_confirm !== 'skipped'

  return (
    <div className="graph-wrap" data-testid="langgraph-flow">
      <svg viewBox="0 0 1060 285" style={{ width: '100%', height: 'auto', display: 'block' }}>
        <defs>
          <marker id="arrow-muted" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,1 L7,4 L0,7 Z" fill="rgba(148, 163, 184, 0.45)" />
          </marker>
          <marker id="arrow-cyan" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,1 L7,4 L0,7 Z" fill="#38bdf8" />
          </marker>
          <marker id="arrow-amber" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,1 L7,4 L0,7 Z" fill="#f59e0b" />
          </marker>
          <marker id="arrow-rose" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,1 L7,4 L0,7 Z" fill="#f43f5e" />
          </marker>
        </defs>

        {/* START */}
        <circle cx="34" cy="110" r="16" fill="rgba(56, 189, 248, 0.14)" stroke="#38bdf8" strokeWidth="1.5" />
        <text x="34" y="114" textAnchor="middle" fill="#bae6fd" fontSize="9.5" fontWeight="700">
          START
        </text>
        <line
          x1="50"
          y1="110"
          x2="105"
          y2="110"
          stroke={edgeColor(nodeStates.extract_anomaly !== 'idle')}
          strokeWidth="2"
          markerEnd="url(#arrow-cyan)"
        />

        {/* extract -> retrieve */}
        <line
          x1="260"
          y1="110"
          x2="295"
          y2="110"
          stroke={edgeColor(nodeStates.retrieve_and_tools !== 'idle')}
          strokeWidth="2"
          markerEnd={nodeStates.retrieve_and_tools !== 'idle' ? 'url(#arrow-cyan)' : 'url(#arrow-muted)'}
        />

        {/* retrieve -> evaluate */}
        <line
          x1="450"
          y1="110"
          x2="490"
          y2="110"
          stroke={edgeColor(nodeStates.evaluate_relevance !== 'idle')}
          strokeWidth="2"
          markerEnd={nodeStates.evaluate_relevance !== 'idle' ? 'url(#arrow-cyan)' : 'url(#arrow-muted)'}
        />

        {/* evaluate -> high_risk_check */}
        <line
          x1="645"
          y1="110"
          x2="685"
          y2="110"
          stroke={edgeColor(nodeStates.high_risk_check !== 'idle')}
          strokeWidth="2"
          markerEnd={nodeStates.high_risk_check !== 'idle' ? 'url(#arrow-cyan)' : 'url(#arrow-muted)'}
        />

        {/* evaluate <-> rewrite_and_retry loop */}
        <path
          d="M 550 144 L 550 204"
          fill="none"
          stroke={edgeColor(retryTaken, true)}
          strokeWidth={retryTaken ? 2.2 : 1.5}
          strokeDasharray={retryTaken ? undefined : '4 4'}
          markerEnd={retryTaken ? 'url(#arrow-amber)' : 'url(#arrow-muted)'}
        />
        <path
          d="M 595 204 L 595 144"
          fill="none"
          stroke={edgeColor(retryTaken, true)}
          strokeWidth={retryTaken ? 2.2 : 1.5}
          strokeDasharray={retryTaken ? undefined : '4 4'}
          markerEnd={retryTaken ? 'url(#arrow-amber)' : 'url(#arrow-muted)'}
        />
        <text x="518" y="182" textAnchor="end" fill={retryTaken ? '#fcd34d' : '#64748b'} fontSize="10">
          低相关 (&lt;0.45)
        </text>
        <text x="606" y="182" textAnchor="start" fill={retryTaken ? '#fcd34d' : '#64748b'} fontSize="10">
          重检回环
        </text>

        {/* high_risk_check -> generate_report (direct safe path) */}
        <line
          x1="840"
          y1="110"
          x2="885"
          y2="110"
          stroke={edgeColor(nodeStates.generate_report !== 'idle' && !hitlTaken)}
          strokeWidth="2"
          markerEnd={
            nodeStates.generate_report !== 'idle' && !hitlTaken ? 'url(#arrow-cyan)' : 'url(#arrow-muted)'
          }
        />
        <text x="862" y="99" textAnchor="middle" fill="#64748b" fontSize="9.5">
          安全
        </text>

        {/* high_risk_check -> human_confirm -> generate_report */}
        <path
          d="M 765 144 L 765 204"
          fill="none"
          stroke={hitlTaken ? '#f43f5e' : 'rgba(148, 163, 184, 0.25)'}
          strokeWidth={hitlTaken ? 2.3 : 1.5}
          strokeDasharray={hitlTaken ? undefined : '4 4'}
          markerEnd={hitlTaken ? 'url(#arrow-rose)' : 'url(#arrow-muted)'}
        />
        <text x="774" y="182" fill={hitlTaken ? '#fda4af' : '#64748b'} fontSize="10">
          高危拦截
        </text>
        <path
          d="M 840 230 Q 945 230 960 148"
          fill="none"
          stroke={hitlTaken && nodeStates.generate_report !== 'idle' ? '#10b981' : 'rgba(148, 163, 184, 0.25)'}
          strokeWidth={hitlTaken && nodeStates.generate_report !== 'idle' ? 2.2 : 1.5}
          strokeDasharray={hitlTaken && nodeStates.generate_report !== 'idle' ? undefined : '4 4'}
          markerEnd={
            hitlTaken && nodeStates.generate_report !== 'idle' ? 'url(#arrow-cyan)' : 'url(#arrow-muted)'
          }
        />
        <text x="905" y="246" textAnchor="middle" fill="#64748b" fontSize="10">
          {humanApproved === true ? '批准恢复' : humanApproved === false ? '拒绝降级' : 'Interrupt & Resume'}
        </text>

        {/* Circuit breaker arc */}
        {circuitBreakerReason ? (
          <path
            d="M 375 76 Q 630 16 945 76"
            fill="none"
            stroke="#a78bfa"
            strokeWidth="2"
            strokeDasharray="5 3"
          />
        ) : null}
        {circuitBreakerReason ? (
          <text x="640" y="34" textAnchor="middle" fill="#ddd6fe" fontSize="10.5" fontWeight="600">
            熔断直达生成: {circuitBreakerReason}
          </text>
        ) : null}

        {/* Nodes */}
        {NODES.map((n) => {
          const st = nodeStates[n.id] || 'idle'
          const isActive = activeNode === n.id
          const visual = getStyle(st, isActive)
          let extraBadge = ''
          if (n.id === 'evaluate_relevance' && relevanceScore !== null) {
            extraBadge = `score=${relevanceScore.toFixed(2)}`
          } else if (n.id === 'rewrite_and_retry' && retryCount > 0) {
            extraBadge = `retry=${retryCount}`
          } else if (n.id === 'human_confirm' && humanApproved !== null) {
            extraBadge = humanApproved ? '已批准' : '已降级'
          }

          return (
            <g key={n.id} transform={`translate(${n.x}, ${n.y - 34})`}>
              <rect
                width="150"
                height="68"
                rx="11"
                fill={visual.fill}
                stroke={visual.stroke}
                strokeWidth={isActive || st === 'interrupted' ? 2.2 : 1.3}
                className={isActive || st === 'interrupted' ? 'node-pulse' : undefined}
              />
              <text x="12" y="23" fill={visual.text} fontSize="11.5" fontWeight="700" fontFamily="var(--font-mono)">
                {n.label}
              </text>
              <text x="12" y="40" fill="#94a3b8" fontSize="10.5">
                {n.sub}
              </text>
              <text x="12" y="57" fill={visual.stroke} fontSize="10" fontWeight="600">
                {extraBadge || visual.badge}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
