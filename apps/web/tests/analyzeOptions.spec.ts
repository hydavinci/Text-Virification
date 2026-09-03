import { describe, expect, it } from 'vitest'

import {
  AnalyzeOptionsError,
  createAnalyzeOptionsSnapshot
} from '../src/api/analyzeOptions'
import type { AnalyzeOptions } from '../src/types/verification'

const MAX_OPTIONS_BYTES = 64 * 1024

function baseOptions(
  overrides: Partial<AnalyzeOptions> = {}
): AnalyzeOptions {
  return {
    scenario: 'general',
    enableSecurity: true,
    enableSensitive: true,
    enableAdExtreme: false,
    glossary: [],
    bannedWords: [],
    ...overrides
  }
}

function backendPayloadBytes(options: AnalyzeOptions): number {
  return new TextEncoder().encode(
    JSON.stringify({
      scenario: options.scenario,
      enable_security: options.enableSecurity,
      enable_sensitive: options.enableSensitive,
      enable_ad_extreme: options.enableAdExtreme,
      custom_glossary: options.glossary,
      banned_words: options.bannedWords
    })
  ).byteLength
}

function optionsWithSerializedBytes(target: number): AnalyzeOptions {
  const options = baseOptions({
    glossary: Array.from({ length: 500 }, (_, index) => ({
      original: `term-${index}`,
      standard: ''
    }))
  })
  let remaining = target - backendPayloadBytes(options)
  for (const term of options.glossary) {
    const added = Math.min(200, remaining)
    term.standard = 'x'.repeat(added)
    remaining -= added
    if (remaining === 0) {
      break
    }
  }
  if (remaining !== 0 || backendPayloadBytes(options) !== target) {
    throw new Error(`Unable to build ${target}-byte options fixture.`)
  }
  return options
}

describe('createAnalyzeOptionsSnapshot', () => {
  it.each([
    ['U+001C', '\u001c'],
    ['U+001D', '\u001d'],
    ['U+001E', '\u001e'],
    ['U+001F', '\u001f'],
    ['U+0085', '\u0085']
  ])('strips Python whitespace %s from banned words', (_label, whitespace) => {
    const snapshot = createAnalyzeOptionsSnapshot(
      baseOptions({
        bannedWords: [
          `${whitespace}forbidden${whitespace}`,
          whitespace,
          'forbidden'
        ]
      })
    )

    expect(snapshot.bannedWords).toEqual(['forbidden'])
  })

  it('preserves U+FEFF because Python str.strip does not remove it', () => {
    const snapshot = createAnalyzeOptionsSnapshot(
      baseOptions({ bannedWords: ['\ufeffforbidden\ufeff'] })
    )

    expect(snapshot.bannedWords).toEqual(['\ufeffforbidden\ufeff'])
  })

  it('accepts the inclusive backend list and Unicode code-point limits', () => {
    const emoji200 = '😀'.repeat(200)
    const options = baseOptions({
      glossary: Array.from({ length: 500 }, (_, index) => ({
        original: index === 0 ? emoji200 : `term-${index}`,
        standard: index === 0 ? '' : `standard-${index}`
      })),
      bannedWords: [
        emoji200,
        ...Array.from({ length: 499 }, (_, index) => `word-${index}`)
      ]
    })

    const snapshot = createAnalyzeOptionsSnapshot(options)

    expect(Array.from(snapshot.glossary[0].original)).toHaveLength(200)
    expect(Array.from(snapshot.bannedWords[0])).toHaveLength(200)
    expect(snapshot.glossary).toHaveLength(500)
    expect(snapshot.bannedWords).toHaveLength(500)
  })

  it.each([
    [
      '501 glossary terms',
      baseOptions({
        glossary: Array.from({ length: 501 }, (_, index) => ({
          original: `term-${index}`,
          standard: `standard-${index}`
        }))
      })
    ],
    [
      '501 banned words',
      baseOptions({
        bannedWords: Array.from({ length: 501 }, (_, index) => `word-${index}`)
      })
    ],
    [
      'a 201-code-point glossary original',
      baseOptions({
        glossary: [{ original: '😀'.repeat(201), standard: '' }]
      })
    ],
    [
      'a 201-code-point glossary standard',
      baseOptions({
        glossary: [{ original: 'term', standard: '😀'.repeat(201) }]
      })
    ],
    [
      'a 201-code-point banned word',
      baseOptions({ bannedWords: ['😀'.repeat(201)] })
    ]
  ])('rejects %s', (_label, options) => {
    expect(() => createAnalyzeOptionsSnapshot(options)).toThrow(
      AnalyzeOptionsError
    )
  })

  it('normalizes terminology with the same canonical backend rules', () => {
    const snapshot = createAnalyzeOptionsSnapshot(
      baseOptions({
        glossary: [
          { original: 'AI', standard: 'AI' },
          { original: 'colour', standard: 'color' }
        ],
        bannedWords: ['  forbidden  ', '', 'forbidden', 'other']
      })
    )

    expect(snapshot.glossary).toEqual([
      { original: 'colour', standard: 'color' }
    ])
    expect(snapshot.bannedWords).toEqual(['forbidden', 'other'])
  })

  it('accepts an exact 64 KiB canonical backend options payload', () => {
    const options = optionsWithSerializedBytes(MAX_OPTIONS_BYTES)

    const snapshot = createAnalyzeOptionsSnapshot(options)

    expect(backendPayloadBytes(snapshot)).toBe(MAX_OPTIONS_BYTES)
  })

  it('rejects a canonical backend options payload one byte over 64 KiB', () => {
    const options = optionsWithSerializedBytes(MAX_OPTIONS_BYTES)
    const expandable = options.glossary.find(
      (term) => Array.from(term.standard).length < 200
    )
    if (!expandable) {
      throw new Error('Expected an expandable glossary term.')
    }
    expandable.standard += 'x'
    expect(backendPayloadBytes(options)).toBe(MAX_OPTIONS_BYTES + 1)

    expect(() => createAnalyzeOptionsSnapshot(options)).toThrow(
      AnalyzeOptionsError
    )
  })

  it('applies Python strip semantics before the serialized-size limit', () => {
    const exact = optionsWithSerializedBytes(MAX_OPTIONS_BYTES)
    exact.bannedWords = ['\u001c']
    expect(backendPayloadBytes(exact)).toBeGreaterThan(MAX_OPTIONS_BYTES)

    expect(() => createAnalyzeOptionsSnapshot(exact)).not.toThrow()

    const oversized = optionsWithSerializedBytes(MAX_OPTIONS_BYTES)
    oversized.bannedWords = ['\ufeff']
    expect(backendPayloadBytes(oversized)).toBeGreaterThan(MAX_OPTIONS_BYTES)

    expect(() => createAnalyzeOptionsSnapshot(oversized)).toThrow(
      AnalyzeOptionsError
    )
  })
})
