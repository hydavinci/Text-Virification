export const EXPORT_TYPE_VALUES = ['modified_document', 'html_report', 'pdf_report'] as const

export type ExportType = (typeof EXPORT_TYPE_VALUES)[number]

export const EXPORT_STATUS_VALUES = ['queued', 'processing', 'completed', 'failed'] as const

export type ExportStatus = (typeof EXPORT_STATUS_VALUES)[number]

export const EXPORT_DISPATCH_STATUS_VALUES = ['dispatched', 'deferred'] as const

export type ExportDispatchStatus = (typeof EXPORT_DISPATCH_STATUS_VALUES)[number]

export interface ExportWarning {
  code: string
  message: string
  issue_id: string
  block_id: string
}

export interface ExportCreateRequest {
  type: ExportType
  version_id?: string
  confirm_warnings?: boolean
}

export interface ExportResponse {
  export_id: string
  job_id: string
  export_type: ExportType
  status: ExportStatus
  file_name: string
  warnings: ExportWarning[]
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  expires_at: string
}

export interface ExportCreateResponse extends ExportResponse {
  dispatch_status: ExportDispatchStatus
}
