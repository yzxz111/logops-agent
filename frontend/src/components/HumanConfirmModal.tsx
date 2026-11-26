import React, { useState } from 'react'
import { AlertTriangle, CheckCircle2, ShieldAlert } from 'lucide-react'
import type { HighRiskInterrupt } from '../types'

interface HumanConfirmModalProps {
  interrupt: HighRiskInterrupt | null
  submitting: boolean
  onConfirm: (approved: boolean, comment: string) => void
}

export const HumanConfirmModal: React.FC<HumanConfirmModalProps> = ({
  interrupt,
  submitting,
  onConfirm,
}) => {
  const [comment, setComment] = useState('已完成流量摘除与备份，按安全审批恢复状态机')

  if (!interrupt) return null

  return (
    <div className="modal-backdrop" data-testid="hitl-modal">
      <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="hitl-title">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: 10,
              display: 'grid',
              placeItems: 'center',
              background: 'rgba(244, 63, 94, 0.16)',
              color: '#fb7185',
            }}
          >
            <ShieldAlert size={20} />
          </div>
          <div>
            <h3 id="hitl-title" style={{ margin: 0, fontSize: 16, color: '#fff1f2' }}>
              HITL 高危运维操作人工确认（Interrupt）
            </h3>
            <div style={{ fontSize: 12, color: '#94a3b8', fontFamily: 'var(--font-mono)' }}>
              thread_id={interrupt.thread_id} · request_id={interrupt.request_id}
            </div>
          </div>
        </div>

        <p style={{ margin: '8px 0 12px', color: '#cbd5e1', fontSize: 13 }}>
          {interrupt.message || '检测到高危运维操作，状态机已在 human_confirm 节点挂起，等待人工审批。'}
        </p>

        <div className="danger-list">
          {interrupt.high_risk_actions.map((act) => (
            <div key={act.action_id} className="danger-item">
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, color: '#fda4af' }}>
                <AlertTriangle size={14} />
                <code>{act.action_id}</code>
              </div>
              <div style={{ fontSize: 12.5, color: '#fecdd3', marginTop: 3 }}>{act.description}</div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 12 }}>
          <label
            htmlFor="hitl-comment"
            style={{ display: 'block', fontSize: 12, color: '#94a3b8', marginBottom: 6 }}
          >
            人工审批备注（写入诊断报告审计栏）
          </label>
          <input
            id="hitl-comment"
            type="text"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="输入审批意见或安全降级说明..."
            style={{
              width: '100%',
              padding: '9px 12px',
              borderRadius: 8,
              border: '1px solid rgba(148, 163, 184, 0.28)',
              background: '#080e1a',
              color: '#f1f5f9',
              fontSize: 13,
            }}
          />
        </div>

        <div className="modal-actions">
          <button
            type="button"
            className="btn-danger-reject"
            disabled={submitting}
            onClick={() => onConfirm(false, comment || '拒绝高危命令，降级为只读建议')}
            data-testid="hitl-reject-btn"
          >
            拒绝高危操作 · 降级只读建议
          </button>
          <button
            type="button"
            className="btn-danger-approve"
            disabled={submitting}
            onClick={() => onConfirm(true, comment || '人工确认批准执行')}
            data-testid="hitl-approve-btn"
          >
            <CheckCircle2 size={14} style={{ verticalAlign: '-2px', marginRight: 5 }} />
            {submitting ? '正在恢复状态机...' : '确认安全条件 · 批准恢复'}
          </button>
        </div>
      </div>
    </div>
  )
}
