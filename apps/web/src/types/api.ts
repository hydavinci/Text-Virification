import type { ExportWarning } from './exports'

export interface StructuredApiErrorDetail {
  code: string
  message: string
  warnings?: ExportWarning[]
}

export interface StructuredApiErrorResponse {
  detail: StructuredApiErrorDetail
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: StructuredApiErrorDetail

  constructor(status: number, detail: StructuredApiErrorDetail) {
    super(detail.message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}
