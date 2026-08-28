export type Scenario = 'general' | 'academic' | 'business' | 'legal' | 'news' | 'technical'
export type IssueSeverity = 'error' | 'warning' | 'info'
export type IssueState = 'pending' | 'accepted' | 'rejected'

export interface GlossaryTerm {
  original: string
  standard: string
}

export interface VerificationIssue {
  type: string
  severity: IssueSeverity
  original: string
  suggestion: string
  position: number
  end_position: number
  context: string
  description: string
  rule_id: string
  alternatives?: string[] | null
  layer: string
  review?: string
  review_reason?: string
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
