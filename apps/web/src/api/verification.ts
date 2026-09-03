import type {
  AnalyzeOptions,
  DraftDocumentRevision,
  ExportArtifactReference,
  ExportReplacement,
  PersistedDocumentRevision,
  VerificationResult
} from '../types/verification'
import type { InjectionKey } from 'vue'
import {
  appendAnalyzeOptions,
  createAnalyzeOptionsSnapshot
} from './analyzeOptions'
import {
  ApiResponseValidationError,
  readApiRequestError
} from './errors'
import { createVerificationResultSnapshot } from '../composables/useVerificationWorkspace'

const API_BASE = '/api/v1'

export interface VerificationApi {
  analyzeFile(file: File, options: AnalyzeOptions): Promise<VerificationResult>
  analyzeText(text: string, options: AnalyzeOptions): Promise<VerificationResult>
  exportReport(result: VerificationResult): Promise<void>
  exportOriginal(
    result: VerificationResult,
    replacements: ExportReplacement[],
    modifiedText: string,
    trackChanges: boolean
  ): Promise<void>
  persistRevision(
    jobId: string,
    revision: DraftDocumentRevision
  ): Promise<PersistedDocumentRevision>
  exportJob(
    jobId: string,
    format: ExportArtifactReference['format'],
    revisionId: string | null,
    trackChanges: boolean,
    isCurrent: () => boolean
  ): Promise<void>
}

export const verificationApiKey: InjectionKey<VerificationApi> = Symbol('verificationApi')

export function createVerificationApi(fetchImpl: typeof fetch = fetch): VerificationApi {
  async function analyze(source: { file?: File; text?: string }, options: AnalyzeOptions) {
    const body = new FormData()
    const snapshot = createAnalyzeOptionsSnapshot(options)
    if (source.file) {
      body.append('file', source.file, source.file.name)
    }
    if (source.text) {
      body.append('text', source.text)
    }
    appendAnalyzeOptions(body, snapshot)

    const response = await fetchImpl(`${API_BASE}/analyze`, { method: 'POST', body })
    if (!response.ok) {
      throw await readApiRequestError(response)
    }
    const result = createVerificationResultSnapshot(await response.json())
    if (result === null) {
      throw new ApiResponseValidationError(
        'Invalid verification result response.'
      )
    }
    return result
  }

  return {
    analyzeFile: (file, options) => analyze({ file }, options),
    analyzeText: (text, options) => analyze({ text }, options),
    exportReport: async (result) => {
      const response = await fetchImpl(`${API_BASE}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(result)
      })
      await downloadResponse(response, '原文检查报告.html')
    },
    exportOriginal: async (result, replacements, modifiedText, trackChanges) => {
      const response = await fetchImpl(`${API_BASE}/export-original`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_id: result.file_id,
          filename: result.filename,
          replacements,
          modified_text: modifiedText,
          track_changes: trackChanges
        })
      })
      await downloadResponse(response, `修改版_${result.filename}`)
    },
    persistRevision: async (jobId, revision) => {
      const response = await fetchImpl(`${API_BASE}/jobs/${jobId}/revisions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          revision_id: revision.revision_id,
          document_id: revision.document_id,
          verification_run_id: revision.verification_run_id,
          source_version: revision.source_version,
          parent_revision_id: revision.parent_revision_id,
          kind: revision.kind,
          text: revision.text
        })
      })
      if (!response.ok) {
        throw await readApiRequestError(response)
      }
      const persisted = persistedRevisionResponse(
        await response.json(),
        revision
      )
      if (persisted === null) {
        throw new ApiResponseValidationError(
          'Invalid persisted revision response.'
        )
      }
      return persisted
    },
    exportJob: async (
      jobId,
      format,
      revisionId,
      trackChanges,
      isCurrent
    ) => {
      const response = await fetchImpl(`${API_BASE}/jobs/${jobId}/exports`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          format,
          revision_id: revisionId,
          track_changes: trackChanges
        })
      })
      if (!isCurrent()) {
        return
      }
      if (!response.ok) {
        const error = await readApiRequestError(response)
        if (!isCurrent()) {
          return
        }
        throw error
      }
      const payload = await response.json()
      if (!isCurrent()) {
        return
      }
      const artifact = exportArtifactResponse(payload, jobId, format)
      if (artifact === null) {
        throw new ApiResponseValidationError(
          'Invalid job export response.'
        )
      }
      const download = await fetchImpl(
        `${API_BASE}/jobs/${jobId}/exports/${artifact.export_artifact_id}`
      )
      if (!isCurrent()) {
        return
      }
      await downloadResponse(download, artifact.file_name, isCurrent)
    }
  }
}

function persistedRevisionResponse(
  value: unknown,
  draft: DraftDocumentRevision
): PersistedDocumentRevision | null {
  if (!isRecord(value)) {
    return null
  }
  const createdAt = parseIsoDate(value.created_at)
  if (
    value.revision_id !== draft.revision_id ||
    value.document_id !== draft.document_id ||
    value.verification_run_id !== draft.verification_run_id ||
    value.source_version !== draft.source_version ||
    value.parent_revision_id !== draft.parent_revision_id ||
    value.kind !== draft.kind ||
    value.text !== draft.text ||
    value.persistence_state !== 'persisted' ||
    !Number.isInteger(value.revision_number) ||
    Number(value.revision_number) <= 0 ||
    createdAt === null
  ) {
    return null
  }
  return Object.freeze({
    revision_id: draft.revision_id,
    document_id: draft.document_id,
    verification_run_id: draft.verification_run_id,
    source_version: draft.source_version,
    revision_number: Number(value.revision_number),
    created_at: createdAt,
    parent_revision_id: draft.parent_revision_id,
    persistence_state: 'persisted',
    kind: draft.kind,
    text: draft.text
  })
}

function exportArtifactResponse(
  value: unknown,
  jobId: string,
  format: ExportArtifactReference['format']
): ExportArtifactReference | null {
  if (
    !isRecord(value) ||
    !isUuid(value.export_artifact_id) ||
    value.job_id !== jobId ||
    !isUuid(value.verification_run_id) ||
    value.format !== format ||
    !['docx', 'doc', 'pdf', 'txt', 'rtf', 'md', 'csv'].includes(
      String(value.file_type)
    ) ||
    (format === 'docx_reconstruction' && value.file_type !== 'docx') ||
    typeof value.file_name !== 'string' ||
    value.file_name.length === 0 ||
    typeof value.media_type !== 'string' ||
    !Number.isInteger(value.size_bytes) ||
    Number(value.size_bytes) < 0 ||
    typeof value.content_sha256 !== 'string' ||
    !/^[0-9a-f]{64}$/.test(value.content_sha256) ||
    value.status !== 'ready' ||
    parseIsoDate(value.created_at) === null
  ) {
    return null
  }
  return value as unknown as ExportArtifactReference
}

function parseIsoDate(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? null : date.toISOString()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isUuid(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value
    )
  )
}

async function downloadResponse(
  response: Response,
  fallbackName: string,
  isCurrent: () => boolean = () => true
) {
  if (!response.ok) {
    const error = await readApiRequestError(response)
    if (!isCurrent()) {
      return
    }
    throw error
  }
  const blob = await response.blob()
  if (!isCurrent()) {
    return
  }
  const disposition = response.headers.get('content-disposition') ?? ''
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  const filename = encodedName ? decodeURIComponent(encodedName) : (plainName ?? fallbackName)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
