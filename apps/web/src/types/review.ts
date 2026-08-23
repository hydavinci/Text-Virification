export const FILE_TYPE_VALUES = ['docx', 'pdf', 'txt'] as const

export type FileType = (typeof FILE_TYPE_VALUES)[number]

export const CHECK_SCENARIO_VALUES = [
  'general',
  'academic',
  'business',
  'legal',
  'news',
  'technical'
] as const

export type CheckScenario = (typeof CHECK_SCENARIO_VALUES)[number]

export const CHECK_CATEGORY_VALUES = [
  'character',
  'vocabulary',
  'sentence',
  'format',
  'discourse',
  'security'
] as const

export type CheckCategory = (typeof CHECK_CATEGORY_VALUES)[number]

export const ISSUE_SEVERITY_VALUES = ['error', 'warning', 'info'] as const

export type IssueSeverity = (typeof ISSUE_SEVERITY_VALUES)[number]

export const DECISION_ACTION_VALUES = ['accepted', 'ignored', 'unreviewed'] as const

export type DecisionAction = (typeof DECISION_ACTION_VALUES)[number]

export const ISSUE_DECISION_VALUES = ['accepted', 'ignored', 'unreviewed'] as const

export type IssueDecisionState = (typeof ISSUE_DECISION_VALUES)[number]

export const DECISION_OUTCOME_STATUS_VALUES = ['applied', 'conflict', 'invalid'] as const

export type DecisionOutcomeStatus = (typeof DECISION_OUTCOME_STATUS_VALUES)[number]

export const TEXT_BLOCK_KIND_VALUES = [
  'paragraph',
  'heading',
  'table_cell',
  'header',
  'footer'
] as const

export type TextBlockKind = (typeof TEXT_BLOCK_KIND_VALUES)[number]

export interface CheckerFailure {
  code: string
  message: string
}
