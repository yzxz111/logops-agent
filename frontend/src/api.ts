import type {
  CitationItem,
  DiagnoseResult,
  EvalReportPayload,
  HealthInfo,
  HighRiskInterrupt,
  RagSearchResponse,
  SearchMode,
  SourceFilePayload,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') || ''

function buildUrl(path: string): string {
  return `${API_BASE}${path}`
}

export async function fetchHealth(requestId?: string): Promise<HealthInfo> {
  const res = await fetch(buildUrl('/health'), {
    headers: requestId ? { 'X-Request-ID': requestId } : undefined,
  })
  if (!res.ok) throw new Error(`健康检查失败 (HTTP ${res.status})`)
  return res.json()
}

export interface StreamHandlers {
  onStart?: (data: {
    request_id: string
    thread_id: string
    max_steps?: number
    token_budget?: number
  }) => void
  onNodeUpdate?: (data: {
    node: string
    step_count?: number
    token_used?: number
    circuit_breaker_reason?: string
    extracted_signals?: Record<string, unknown>
    redaction_counts?: Record<string, number>
    rewritten_queries?: string[]
    rag_citations?: CitationItem[]
    tool_calls?: DiagnoseResult['tool_calls']
    relevance_score?: number
    is_relevant?: boolean
    retry_count?: number
    requires_human_confirm?: boolean
    high_risk_actions?: DiagnoseResult['high_risk_actions']
  }) => void
  onHumanConfirmRequired?: (data: HighRiskInterrupt) => void
  onToken?: (data: { delta: string; request_id: string }) => void
  onDone?: (data: DiagnoseResult) => void
  onError?: (err: Error) => void
}

export async function streamDiagnose(
  params: {
    query: string
    requestId: string
    maxSteps?: number
    tokenBudget?: number
    signal?: AbortSignal
  },
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch(buildUrl('/api/v1/diagnose/stream'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Request-ID': params.requestId,
    },
    body: JSON.stringify({
      query: params.query,
      max_steps: params.maxSteps,
      token_budget: params.tokenBudget,
    }),
    signal: params.signal,
  })

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => '')
    throw new Error(`流式诊断启动失败 (HTTP ${res.status}): ${text}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let currentEvent = 'message'
  let dataLines: string[] = []

  const dispatchEvent = () => {
    if (dataLines.length === 0) return
    const rawData = dataLines.join('\n').trim()
    dataLines = []
    if (!rawData || rawData === '[DONE]') return

    try {
      const parsed = JSON.parse(rawData)
      if (currentEvent === 'start') handlers.onStart?.(parsed)
      else if (currentEvent === 'node_update') handlers.onNodeUpdate?.(parsed)
      else if (currentEvent === 'human_confirm_required') handlers.onHumanConfirmRequired?.(parsed)
      else if (currentEvent === 'token') handlers.onToken?.(parsed)
      else if (currentEvent === 'done') handlers.onDone?.(parsed)
    } catch {
      // 忽略无法解析的保活行
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      dispatchEvent()
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (line === '') {
        dispatchEvent()
        currentEvent = 'message'
        continue
      }
      if (line.startsWith('event:')) {
        currentEvent = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart())
      }
    }
  }
}

export async function confirmHighRisk(
  threadId: string,
  approved: boolean,
  comment: string,
  requestId: string,
): Promise<DiagnoseResult> {
  const res = await fetch(buildUrl(`/api/v1/diagnose/${encodeURIComponent(threadId)}/confirm`), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Request-ID': requestId,
    },
    body: JSON.stringify({ approved, comment }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`人工确认恢复失败 (HTTP ${res.status}): ${text}`)
  }
  return res.json()
}

export async function fetchSourceFile(
  path: string,
  startLine = 1,
  endLine?: number,
): Promise<SourceFilePayload> {
  const qs = new URLSearchParams({
    path,
    start_line: String(Math.max(1, startLine)),
  })
  if (endLine && endLine >= startLine) {
    qs.set('end_line', String(endLine))
  }
  const res = await fetch(buildUrl(`/api/v1/source/file?${qs.toString()}`))
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`读取溯源文件失败 (HTTP ${res.status}): ${text}`)
  }
  return res.json()
}

export async function fetchEvalReport(): Promise<EvalReportPayload> {
  const res = await fetch(buildUrl('/api/v1/eval/report'))
  if (!res.ok) throw new Error(`获取评测报告失败 (HTTP ${res.status})`)
  return res.json()
}

export async function rerunEvalReport(): Promise<EvalReportPayload> {
  const res = await fetch(buildUrl('/api/v1/eval/run'), { method: 'POST' })
  if (!res.ok) throw new Error(`重跑评测失败 (HTTP ${res.status})`)
  return res.json()
}

export async function searchRag(
  query: string,
  mode: SearchMode,
  topK = 3,
): Promise<RagSearchResponse> {
  const res = await fetch(buildUrl('/api/v1/rag/search'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, mode, top_k: topK }),
  })
  if (!res.ok) throw new Error(`RAG 检索对比失败 (HTTP ${res.status})`)
  return res.json()
}
