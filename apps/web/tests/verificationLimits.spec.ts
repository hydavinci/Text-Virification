import { describe, expect, it } from 'vitest'

import {
  MAX_DIRECT_TEXT_CODE_POINTS,
  MAX_DIRECT_TEXT_UTF8_BYTES,
  MAX_VERIFICATION_ISSUES,
  isVerificationIssueCountAllowed,
  unicodeCodePointLength,
  validateDirectText
} from '../src/validation/verificationLimits'

describe('verification limits', () => {
  it('matches the backend direct-text and canonical issue limits', () => {
    expect(MAX_DIRECT_TEXT_CODE_POINTS).toBe(5_000_000)
    expect(MAX_DIRECT_TEXT_UTF8_BYTES).toBe(25 * 1024 * 1024)
    expect(MAX_VERIFICATION_ISSUES).toBe(100_000)
  })

  it('uses Python-equivalent whitespace emptiness without stripping FEFF', () => {
    expect(validateDirectText(' \t\r\n\u001c\u001d\u001e\u001f\u0085')).toBe(
      'empty'
    )
    expect(validateDirectText('\ufeff')).toBeNull()
    expect(validateDirectText(` \ufeff `)).toBeNull()
  })

  it('enforces inclusive Unicode code-point and UTF-8 byte limits', () => {
    expect(
      validateDirectText('😀a', {
        maxCodePoints: 2,
        maxUtf8Bytes: 5
      })
    ).toBeNull()
    expect(
      validateDirectText('😀ab', {
        maxCodePoints: 2,
        maxUtf8Bytes: 6
      })
    ).toBe('too_many_code_points')
    expect(
      validateDirectText('😀ab', {
        maxCodePoints: 3,
        maxUtf8Bytes: 5
      })
    ).toBe('too_many_utf8_bytes')
    expect(unicodeCodePointLength('😀a')).toBe(2)
  })

  it('accepts the exact canonical issue limit and rejects one over', () => {
    expect(isVerificationIssueCountAllowed(MAX_VERIFICATION_ISSUES)).toBe(true)
    expect(isVerificationIssueCountAllowed(MAX_VERIFICATION_ISSUES + 1)).toBe(
      false
    )
  })
})
