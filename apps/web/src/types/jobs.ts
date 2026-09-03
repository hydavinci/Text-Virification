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

export const JOB_FILE_TYPE_VALUES = [
  'docx',
  'doc',
  'pdf',
  'txt',
  'rtf',
  'md',
  'csv'
] as const

export type JobFileType = (typeof JOB_FILE_TYPE_VALUES)[number]

export const JOB_PROGRESS_STAGE_VALUES = [
  'queued',
  'upload_validated',
  'parsing',
  'ocr',
  'checking_format',
  'checking_sensitive',
  'checking_chinese',
  'checking_english',
  'exporting',
  'finalizing',
  'completed',
  'partial',
  'failed',
  'expired'
] as const

export type JobProgressStage = (typeof JOB_PROGRESS_STAGE_VALUES)[number]

export const TERMINAL_JOB_STATUSES = ['completed', 'partial', 'failed', 'expired'] as const

export type JobTerminalStatus = (typeof TERMINAL_JOB_STATUSES)[number]

export interface JobRead {
  job_id: string
  source_name: string
  file_type: JobFileType
  size_bytes: number
  status: JobStatus
  stage: JobProgressStage
  progress: number
  error_code: string | null
  error_message: string | null
  error_stage: string | null
  error_retryable: boolean | null
  created_at: string
  expires_at: string
}

export interface JobProgressEvent {
  sequence: number
  status: JobStatus
  stage: JobProgressStage
  progress: number
  message: string
  created_at: string
}

export function isTerminalJobStatus(status: JobStatus): status is JobTerminalStatus {
  return TERMINAL_JOB_STATUSES.includes(status as JobTerminalStatus)
}
