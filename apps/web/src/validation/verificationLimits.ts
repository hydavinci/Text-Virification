import { isPythonWhitespace } from '../api/pythonWhitespace'

export const MAX_DIRECT_TEXT_CODE_POINTS = 5_000_000
export const MAX_DIRECT_TEXT_UTF8_BYTES = 25 * 1024 * 1024
export const MAX_VERIFICATION_ISSUES = 100_000

export type DirectTextValidationError =
  | 'empty'
  | 'too_many_code_points'
  | 'too_many_utf8_bytes'

interface DirectTextLimits {
  maxCodePoints?: number
  maxUtf8Bytes?: number
}

export function unicodeCodePointLength(value: string): number {
  let length = 0
  for (const _character of value) {
    length += 1
  }
  return length
}

export function validateDirectText(
  value: string,
  limits: DirectTextLimits = {}
): DirectTextValidationError | null {
  const maxCodePoints =
    limits.maxCodePoints ?? MAX_DIRECT_TEXT_CODE_POINTS
  const maxUtf8Bytes =
    limits.maxUtf8Bytes ?? MAX_DIRECT_TEXT_UTF8_BYTES
  let codePoints = 0
  let hasContent = false

  for (const character of value) {
    codePoints += 1
    if (codePoints > maxCodePoints) {
      return 'too_many_code_points'
    }
    if (!isPythonWhitespace(character)) {
      hasContent = true
    }
  }
  if (!hasContent) {
    return 'empty'
  }
  if (new TextEncoder().encode(value).byteLength > maxUtf8Bytes) {
    return 'too_many_utf8_bytes'
  }
  return null
}

export function isVerificationIssueCountAllowed(count: number): boolean {
  return (
    Number.isInteger(count) &&
    count >= 0 &&
    count <= MAX_VERIFICATION_ISSUES
  )
}
