export interface ApiErrorDetails {
  code: string | null
  stage: string | null
  message: string
  retryable: boolean | null
}

export class ApiRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string | null,
    message: string,
    public readonly stage: string | null = null,
    public readonly retryable: boolean | null = null
  ) {
    super(message)
    this.name = 'ApiRequestError'
  }
}

export async function readApiRequestError(
  response: Response,
  fallbackMessage = `请求失败（${response.status}）`
): Promise<ApiRequestError> {
  const details = await readApiErrorDetails(response, fallbackMessage)
  return new ApiRequestError(
    response.status,
    details.code,
    details.message,
    details.stage,
    details.retryable
  )
}

async function readApiErrorDetails(
  response: Response,
  fallbackMessage: string
): Promise<ApiErrorDetails> {
  try {
    const payload: unknown = await response.json()
    if (!isRecord(payload)) {
      return emptyDetails(fallbackMessage)
    }
    const detail = payload.detail
    if (typeof detail === 'string' && detail.trim()) {
      return {
        code: stringOrNull(payload.code),
        stage: stringOrNull(payload.stage),
        message: detail,
        retryable: booleanOrNull(payload.retryable)
      }
    }
    if (isRecord(detail)) {
      return {
        code: stringOrNull(detail.code),
        stage: stringOrNull(detail.stage),
        message: nonemptyString(detail.message) ?? fallbackMessage,
        retryable: booleanOrNull(detail.retryable)
      }
    }
    return {
      code: stringOrNull(payload.code),
      stage: stringOrNull(payload.stage),
      message:
        nonemptyString(payload.message) ??
        nonemptyString(payload.error) ??
        fallbackMessage,
      retryable: booleanOrNull(payload.retryable)
    }
  } catch {
    return emptyDetails(fallbackMessage)
  }
}

function emptyDetails(message: string): ApiErrorDetails {
  return {
    code: null,
    stage: null,
    message,
    retryable: null
  }
}

function nonemptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function stringOrNull(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function booleanOrNull(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
