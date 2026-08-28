import type {
  AnalyzeOptions,
  ExportReplacement,
  VerificationResult
} from '../types/verification'
import type { InjectionKey } from 'vue'

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
    if (source.file) {
      body.append('file', source.file, source.file.name)
    }
    if (source.text) {
      body.append('text', source.text)
    }
    body.append('scenario', options.scenario)
    body.append('enable_security', String(options.enableSecurity))
    body.append('enable_sensitive', String(options.enableSensitive))
    body.append('enable_ad_extreme', String(options.enableAdExtreme))
    body.append('custom_glossary', JSON.stringify(options.glossary))
    body.append('banned_words', JSON.stringify(options.bannedWords))

    const response = await fetchImpl(`${API_BASE}/analyze`, { method: 'POST', body })
    if (!response.ok) {
      throw new Error(await extractError(response))
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

async function extractError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as {
      detail?: string | { message?: string }
      error?: string
    }
    if (typeof payload.detail === 'string') {
      return payload.detail
    }
    return payload.detail?.message ?? payload.error ?? `请求失败（${response.status}）`
  } catch {
    return `请求失败（${response.status}）`
  }
}

async function downloadResponse(response: Response, fallbackName: string) {
  if (!response.ok) {
    throw new Error(await extractError(response))
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
