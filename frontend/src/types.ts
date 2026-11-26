export type SearchMode = 'bm25_only' | 'vector_only' | 'hybrid_rrf' | 'agentic'

export interface HealthInfo {
  status: string
  app_name: string
  version: string
  llm_provider: string
  indexed_chunks: number
  request_id: string
}

export interface CitationItem {
  chunk_id: string
  doc_id: string
  title: string
  service: string
  error_code: string
  section: string
  source_path: string
  line_range: string
  score: number
  snippet: string
}

export interface ToolLocation {
  path: string
  start_line: number
  end_line: number
  matched_line: number
}

export interface ToolCallItem {
  tool: string
  args: Record<string, unknown>
  total_matches: number
  raw_chars: number
  compressed_chars: number
  locations?: ToolLocation[]
}

export interface ExtractedSignals {
  service?: string
  error_codes?: string[]
  exception_classes?: string[]
  trace_id?: string
  log_keyword?: string
  source_keyword?: string
}

export interface HighRiskAction {
  action_id: string
  description: string
}

export interface DiagnoseResult {
  request_id: string
  thread_id: string
  status: string
  root_cause: string
  final_report: string
  rag_citations: CitationItem[]
  tool_calls: ToolCallItem[]
  rewritten_queries: string[]
  relevance_score: number
  retry_count: number
  step_count: number
  token_used: number
  circuit_breaker_reason: string
  requires_human_confirm: boolean
  high_risk_actions: HighRiskAction[]
  human_approved: boolean | null
  redaction_counts: Record<string, number>
  extracted_signals?: ExtractedSignals
  trace_events?: Array<Record<string, unknown>>
  interrupt?: HighRiskInterrupt | null
}

export interface HighRiskInterrupt {
  type?: string
  thread_id: string
  request_id: string
  message: string
  high_risk_actions: HighRiskAction[]
  snapshot?: Partial<DiagnoseResult>
}

export type GraphNodeId =
  | 'extract_anomaly'
  | 'retrieve_and_tools'
  | 'evaluate_relevance'
  | 'rewrite_and_retry'
  | 'high_risk_check'
  | 'human_confirm'
  | 'generate_report'

export type NodeVisualStatus =
  | 'idle'
  | 'active'
  | 'completed'
  | 'interrupted'
  | 'retried'
  | 'skipped'

export interface NodeTimelineItem {
  step: number
  node: string
  detail: string
  timestamp: string
}

export interface SourceFileLine {
  line_number: number
  content: string
}

export interface SourceFilePayload {
  request_id: string
  path: string
  language: string
  total_lines: number
  highlight_start: number
  highlight_end: number
  lines: SourceFileLine[]
}

export interface RagModeMetrics {
  'Recall@1': number
  'Recall@3': number
  'Recall@5': number
  MRR: number
}

export interface EvalCaseDetail {
  id: string
  query: string
  difficulty: string
  expected_doc_ids: string[]
  expected_service: string
  has_high_risk_action: boolean
  status: string
  top_doc: string | null
  tools: string[]
  tool_matched: boolean
  root_cause_matched: boolean
  steps: number
  tokens: number
  retry_count: number
}

export interface EvalReportPayload {
  request_id: string
  total_cases: number
  indexed_chunks: number
  rag_comparison: Record<SearchMode, RagModeMetrics>
  agent_metrics: {
    tool_accuracy: number
    root_cause_hit_rate: number
    high_risk_interception_rate: number
    secondary_retrieval_triggered_cases: number
    tool_context_compression_ratio: number
  }
  case_details: EvalCaseDetail[]
}

export interface RagSearchResponse {
  request_id: string
  original_query: string
  rewritten_queries: string[]
  mode: SearchMode
  citations: CitationItem[]
}

export interface PresetScenario {
  id: string
  label: string
  tag: string
  tagTone: 'cyan' | 'amber' | 'rose' | 'violet'
  description: string
  query: string
  maxSteps?: number
  tokenBudget?: number
}
