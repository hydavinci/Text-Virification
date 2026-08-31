export type Scenario = 'general' | 'academic' | 'business' | 'legal' | 'news' | 'technical'
export type IssueSeverity = 'error' | 'warning' | 'info'
export type IssueState = 'pending' | 'accepted' | 'rejected'
export type VerificationExecutionMode = 'synchronous' | 'asynchronous'
export type VerificationAnalysisMode = 'local_only' | 'local_plus_llm'

export interface GlossaryTerm {
  original: string
  standard: string
}

export interface VerificationIssue {
  issue_id: string
  document_id: string
  verification_run_id: string
  block_id: string | null
  page: number | null
  start: number
  end: number
  block_start: number | null
  block_end: number | null
  type: string
  severity: IssueSeverity
  original: string
  suggestion: string | null
  alternatives?: string[] | null
  layer: string
  message: string
  description: string
  rule_id: string
  rule_version: string
  source: string
  source_version: string
  confidence: number
  auto_fixable: boolean
  context: string
  position: number
  end_position: number
  review?: string
  review_reason?: string
}

export interface VerificationDegradation {
  is_degraded: boolean
  reasons: string[]
}

export interface VerificationStats {
  char_count: number
  char_count_no_space: number
  line_count: number
  paragraph_count: number
  language: 'zh' | 'en'
  primary_count: number
  primary_label: string
}

export interface VerificationSummary {
  total: number
  by_type: Record<string, number>
  by_severity: Record<string, number>
  by_rule: Record<string, number>
  by_layer: Record<string, number>
  llm_review?: Record<string, unknown>
}

export interface VerificationResult {
  success: boolean
  filename: string
  text: string
  stats: VerificationStats
  issues: VerificationIssue[]
  summary: VerificationSummary
  file_id: string | null
  file_ext: string | null
  document_id: string
  verification_run_id: string
  source_version: string
  execution_mode: VerificationExecutionMode
  analysis_mode: VerificationAnalysisMode
  dictionary_versions: Record<string, string>
  degradation: VerificationDegradation
  scenario: Scenario
}

export interface AnalyzeOptions {
  scenario: Scenario
  enableSecurity: boolean
  enableSensitive: boolean
  enableAdExtreme: boolean
  glossary: GlossaryTerm[]
  bannedWords: string[]
}

export interface ExportReplacement {
  original: string
  suggestion: string
  position: number
  end_position: number
}
