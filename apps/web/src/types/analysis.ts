import type { JobStatus } from './jobs'
import type {
  CheckCategory,
  CheckerFailure,
  DecisionAction,
  DecisionOutcomeStatus,
  FileType,
  IssueDecisionState,
  IssueSeverity,
  TextBlockKind
} from './review'

export type CheckerFailureMap = Partial<Record<CheckCategory, CheckerFailure>>

export interface DocumentPageQuery {
  cursor?: string
  limit?: number
}

export interface IssuesQuery {
  category?: CheckCategory
  severity?: IssueSeverity
  decision?: IssueDecisionState
  search?: string
  cursor?: string
  limit?: number
}

export interface DecisionCommand {
  issue_id: string
  issue_version: number
  action: DecisionAction
  replacement?: string | null
}

export interface IssueDecisionSummary {
  issue_version: number
  action: DecisionAction
  replacement: string | null
  updated_at: string
}

export interface IssueDecision {
  issue_id: string
  issue_version: number
  action: DecisionAction
  replacement: string | null
  updated_at: string
}

export interface DocumentBlock {
  block_id: string
  kind: TextBlockKind
  text: string
  page: number | null
  paragraph_index: number | null
  parent_id: string | null
  style: Record<string, unknown>
  source_locator: Record<string, unknown>
}

export interface Issue {
  issue_id: string
  document_id: string
  document_version: number | null
  block_id: string
  page: number | null
  start: number
  end: number
  original: string
  suggestion: string | null
  alternatives: string[]
  type: string
  severity: IssueSeverity
  layer: string
  message: string
  rule_id: string
  source: string
  source_version: string
  confidence: number
  auto_fixable: boolean
  context: string
  decision: IssueDecisionSummary | null
}

export interface DocumentPageResponse {
  job_id: string
  status: JobStatus
  document_id: string
  file_type: FileType
  source_name: string
  version: number
  metadata: Record<string, unknown>
  blocks: DocumentBlock[]
  total_blocks: number
  next_cursor: string | null
  checker_failures: CheckerFailureMap
}

export interface IssuePageResponse {
  job_id: string
  status: JobStatus
  total: number
  items: Issue[]
  next_cursor: string | null
  checker_failures: CheckerFailureMap
}

export interface AnalysisSummaryResponse {
  job_id: string
  status: JobStatus
  total_issues: number
  by_category: Record<CheckCategory, number>
  by_severity: Record<IssueSeverity, number>
  by_decision: Record<IssueDecisionState, number>
  checker_failures: CheckerFailureMap
}

export interface AppliedDecisionOutcome {
  issue_id: string
  status: Extract<DecisionOutcomeStatus, 'applied'>
  code: null
  decision: IssueDecision
}

export interface NonAppliedDecisionOutcome {
  issue_id: string
  status: Exclude<DecisionOutcomeStatus, 'applied'>
  code: string
  decision: null
}

export type DecisionOutcome = AppliedDecisionOutcome | NonAppliedDecisionOutcome

export interface DecisionBatchResponse {
  outcomes: DecisionOutcome[]
}
