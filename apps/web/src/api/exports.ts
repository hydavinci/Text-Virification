import type { InjectionKey } from 'vue'

import { buildApiPath, requestJson, type RequestJsonDependencies } from './client'
import type { ExportCreateRequest, ExportCreateResponse, ExportResponse } from '../types/exports'

export interface ExportsApi {
  create(jobId: string, request: ExportCreateRequest): Promise<ExportCreateResponse>
  get(jobId: string, exportId: string): Promise<ExportResponse>
  downloadUrl(jobId: string, exportId: string): string
}

interface ExportsApiDependencies extends RequestJsonDependencies {}

export const exportsApiKey: InjectionKey<ExportsApi> = Symbol('exportsApi')

export function createExportsApi(
  overrides: Partial<ExportsApiDependencies> = {}
): ExportsApi {
  const dependencies: ExportsApiDependencies = {
    fetch: overrides.fetch ?? fetch
  }

  return {
    create(jobId, request) {
      return requestJson<ExportCreateResponse>(dependencies, `/jobs/${encodeURIComponent(jobId)}/exports`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request)
      })
    },
    get(jobId, exportId) {
      return requestJson<ExportResponse>(
        dependencies,
        `/jobs/${encodeURIComponent(jobId)}/exports/${encodeURIComponent(exportId)}`
      )
    },
    downloadUrl(jobId, exportId) {
      return buildApiPath(
        `/jobs/${encodeURIComponent(jobId)}/exports/${encodeURIComponent(exportId)}/download`
      )
    }
  }
}
