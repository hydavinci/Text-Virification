import type { CheckCategory, CheckScenario, FileType } from './review'

export const JOB_STATUS_VALUES = [
  'queued',
  'upload_validated',
  'parsing',
  'checking_format',
  'checking_sensitive',
  'checking_chinese',
  'checking_english',
  'completed',
  'partial',
  'failed',
  'expired'
] as const

export type JobStatus = (typeof JOB_STATUS_VALUES)[number]

export const TERMINAL_JOB_STATUSES = ['completed', 'partial', 'failed', 'expired'] as const

export type JobTerminalStatus = (typeof TERMINAL_JOB_STATUSES)[number]

export interface JobCreateOptions {
  scenario?: CheckScenario
  enabledCategories?: CheckCategory[]
}

export interface JobRead {
  job_id: string
  source_name: string
  file_type: FileType
  size_bytes: number
  status: JobStatus
  progress: number
  error_code: string | null
  error_message: string | null
  scenario?: CheckScenario
  enabled_categories?: CheckCategory[]
  created_at: string
  expires_at: string
}

export interface JobProgressEvent {
  sequence: number
  status: JobStatus
  progress: number
  message: string
  created_at: string
}

export function isTerminalJobStatus(status: JobStatus): status is JobTerminalStatus {
  return TERMINAL_JOB_STATUSES.includes(status as JobTerminalStatus)
}
