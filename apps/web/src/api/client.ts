import { ApiError, type StructuredApiErrorDetail, type StructuredApiErrorResponse } from '../types/api'

const API_BASE = '/api/v1'

export interface RequestJsonDependencies {
  fetch: typeof fetch
}

export async function requestJson<T>(
  dependencies: RequestJsonDependencies,
  path: string,
  init?: RequestInit
): Promise<T> {
  const response = await dependencies.fetch.call(globalThis, buildApiPath(path), init)

  if (!response.ok) {
    throw await buildApiError(response)
  }

  return (await response.json()) as T
}

export function buildApiPath(path: string): string {
  return `${API_BASE}${path}`
}

async function buildApiError(response: Response): Promise<ApiError> {
  return new ApiError(response.status, await readErrorDetail(response))
}

async function readErrorDetail(response: Response): Promise<StructuredApiErrorDetail> {
  const fallback = {
    code: 'request_failed',
    message: `Request failed with status ${response.status}.`
  } satisfies StructuredApiErrorDetail

  try {
    const payload = (await response.json()) as unknown
    if (!isStructuredApiErrorResponse(payload)) {
      return fallback
    }

    return payload.detail
  } catch {
    return fallback
  }
}

function isStructuredApiErrorResponse(value: unknown): value is StructuredApiErrorResponse {
  if (!isRecord(value) || !isRecord(value.detail)) {
    return false
  }

  if (typeof value.detail.code !== 'string' || typeof value.detail.message !== 'string') {
    return false
  }

  return value.detail.warnings === undefined || Array.isArray(value.detail.warnings)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
