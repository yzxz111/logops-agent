import React from 'react'

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g)
  return parts.map((part, idx) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
      return <code key={idx}>{part.slice(1, -1)}</code>
    }
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      return <strong key={idx}>{part.slice(2, -2)}</strong>
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>
  })
}

export const MarkdownReport: React.FC<{ content: string }> = ({ content }) => {
  if (!content.trim()) {
    return (
      <div style={{ color: '#64748b', fontSize: 13 }}>
        提交左侧故障描述后，这里将通过 SSE 实时推送 LangGraph 节点事件与流式排障报告...
      </div>
    )
  }

  const lines = content.split(/\r?\n/)
  const elements: React.ReactNode[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith('```')) {
      const codeLines: string[] = []
      i += 1
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i += 1
      }
      elements.push(
        <pre key={`pre-${i}`}>
          <code>{codeLines.join('\n')}</code>
        </pre>,
      )
      i += 1
      continue
    }

    if (line.startsWith('## ')) {
      elements.push(<h2 key={`h2-${i}`}>{renderInline(line.slice(3))}</h2>)
      i += 1
      continue
    }
    if (line.startsWith('### ')) {
      elements.push(<h3 key={`h3-${i}`}>{renderInline(line.slice(4))}</h3>)
      i += 1
      continue
    }
    if (line.startsWith('> ')) {
      elements.push(<blockquote key={`bq-${i}`}>{renderInline(line.slice(2))}</blockquote>)
      i += 1
      continue
    }
    if (line.startsWith('- ')) {
      const items: string[] = []
      while (i < lines.length && lines[i].startsWith('- ')) {
        items.push(lines[i].slice(2))
        i += 1
      }
      elements.push(
        <ul key={`ul-${i}`}>
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ul>,
      )
      continue
    }
    if (line.trim() === '') {
      i += 1
      continue
    }
    elements.push(<p key={`p-${i}`}>{renderInline(line)}</p>)
    i += 1
  }

  return <>{elements}</>
}
