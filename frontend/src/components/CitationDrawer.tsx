import React, { useEffect, useRef } from 'react'
import { FileCode2, FileText, X } from 'lucide-react'
import type { SourceFilePayload } from '../types'

interface CitationDrawerProps {
  open: boolean
  loading: boolean
  error: string
  fileData: SourceFilePayload | null
  titleHint?: string
  onClose: () => void
}

export const CitationDrawer: React.FC<CitationDrawerProps> = ({
  open,
  loading,
  error,
  fileData,
  titleHint,
  onClose,
}) => {
  const firstHighlightRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (open && fileData && firstHighlightRef.current) {
      firstHighlightRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }, [open, fileData])

  if (!open) return null

  return (
    <div className="overlay-backdrop" onClick={onClose} data-testid="citation-drawer-backdrop">
      <aside
        className="drawer-panel"
        onClick={(e) => e.stopPropagation()}
        data-testid="citation-drawer"
      >
        <div className="drawer-header">
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {fileData?.language === 'markdown' ? (
                <FileText size={16} color="#38bdf8" />
              ) : (
                <FileCode2 size={16} color="#38bdf8" />
              )}
              <strong style={{ fontSize: 14, color: '#f1f5f9', wordBreak: 'break-all' }}>
                {fileData?.path || titleHint || '溯源文档预览'}
              </strong>
            </div>
            {fileData ? (
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
                语言: <code>{fileData.language}</code> · 共 {fileData.total_lines} 行 · 高亮区间:{' '}
                <span style={{ color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>
                  L{fileData.highlight_start}-L{fileData.highlight_end}
                </span>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className="btn-secondary"
            onClick={onClose}
            aria-label="关闭溯源抽屉"
            data-testid="close-drawer-btn"
          >
            <X size={15} />
            关闭
          </button>
        </div>

        <div className="drawer-body">
          {loading ? (
            <div style={{ padding: 24, color: '#94a3b8' }}>正在加载真实源码/故障手册内容...</div>
          ) : error ? (
            <div style={{ padding: 24, color: '#fda4af' }}>{error}</div>
          ) : fileData ? (
            <div>
              {fileData.lines.map((line) => {
                const isHighlighted =
                  line.line_number >= fileData.highlight_start &&
                  line.line_number <= fileData.highlight_end
                const isFirst = line.line_number === fileData.highlight_start
                return (
                  <div
                    key={line.line_number}
                    ref={isFirst ? firstHighlightRef : undefined}
                    className={`code-line ${isHighlighted ? 'highlighted' : ''}`}
                    data-highlighted={isHighlighted ? 'true' : 'false'}
                  >
                    <span className="line-no">{line.line_number}</span>
                    <span>{line.content || ' '}</span>
                  </div>
                )
              })}
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  )
}
