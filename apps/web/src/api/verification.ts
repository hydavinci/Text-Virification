import type {
  AnalyzeOptions,
  ExportReplacement,
  VerificationResult
} from '../types/verification'
import type { InjectionKey } from 'vue'
import {
  appendAnalyzeOptions,
  createAnalyzeOptionsSnapshot
} from './analyzeOptions'
import { readApiRequestError } from './errors'

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
    return (await response.json()) as VerificationResult
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
    }
  }
}

async function downloadResponse(response: Response, fallbackName: string) {
  if (!response.ok) {
    throw await readApiRequestError(response)
  }
  const blob = await response.blob()
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
