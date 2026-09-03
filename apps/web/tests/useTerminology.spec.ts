import { describe, expect, it } from 'vitest'

import {
  MAX_TERMINOLOGY_ENTRIES,
  MAX_TERMINOLOGY_IMPORT_BYTES,
  TerminologyImportError,
  glossaryExampleCsv,
  parseBannedWords,
  parseGlossary,
  readTerminologyFile,
  useTerminology
} from '../src/composables/useTerminology'
import type { AnalyzeOptions } from '../src/types/verification'

const MAX_VERIFICATION_OPTIONS_JSON_BYTES = 64 * 1024

function verificationOptionsBytes(options: AnalyzeOptions): number {
  return new TextEncoder().encode(
    JSON.stringify({
      scenario: options.scenario,
      enable_security: options.enableSecurity,
      enable_sensitive: options.enableSensitive,
      enable_ad_extreme: options.enableAdExtreme,
      custom_glossary: options.glossary.map(({ original, standard }) => ({
        original,
        standard
      })),
      banned_words: options.bannedWords
    })
  ).byteLength
}

function buildOptionsAtSerializedSize(
  targetBytes: number,
  overrides: Partial<AnalyzeOptions> = {}
): AnalyzeOptions {
  const options: AnalyzeOptions = {
    scenario: 'general',
    enableSecurity: true,
    enableSensitive: true,
    enableAdExtreme: false,
    glossary: [],
    bannedWords: [],
    ...overrides
  }
  const requiredValueBytes = targetBytes - verificationOptionsBytes(options)

  for (let count = 1; count <= MAX_TERMINOLOGY_ENTRIES; count += 1) {
    const totalWordLength = requiredValueBytes - 3 * count + 1
    if (totalWordLength < 3 * count || totalWordLength > 200 * count) {
      continue
    }

    let remaining = totalWordLength
    options.bannedWords = Array.from({ length: count }, (_, index) => {
      const slotsAfter = count - index - 1
      const length = Math.min(200, remaining - 3 * slotsAfter)
      remaining -= length
      return `${index.toString(36).padStart(3, '0')}${'x'.repeat(length - 3)}`
    })
    expect(verificationOptionsBytes(options)).toBe(targetBytes)
    return options
  }

  throw new Error(`Unable to construct ${targetBytes}-byte options.`)
}

describe('terminology import parsers', () => {
  it('handles a UTF-8 BOM, comments, blanks, quoted CSV, TSV, and arrows', () => {
    expect(
      parseGlossary(
        '\ufeff# note\n\n"AI, ML","人工智能, 机器学习"\nAPP\t应用程序\n帐号 → 账号'
      )
    ).toEqual([
      { original: 'AI, ML', standard: '人工智能, 机器学习' },
      { original: 'APP', standard: '应用程序' },
      { original: '帐号', standard: '账号' }
    ])
  })

  it('parses TSV rows whose values contain commas', () => {
    expect(parseGlossary('AI, ML\t人工智能')).toEqual([
      { original: 'AI, ML', standard: '人工智能' }
    ])
  })

  it('uses only the declared CSV delimiter when values contain arrows or tabs', () => {
    expect(parseGlossary('AI→ML,人工智能', 'csv')).toEqual([
      { original: 'AI→ML', standard: '人工智能' }
    ])
    expect(parseGlossary('"AI\tML",人工智能', 'csv')).toEqual([
      { original: 'AI\tML', standard: '人工智能' }
    ])
  })

  it('uses only the declared TSV delimiter with quoted tabs and commas', () => {
    expect(
      parseGlossary('"AI\tML"\t"人工智能,机器学习"', 'tsv')
    ).toEqual([
      { original: 'AI\tML', standard: '人工智能,机器学习' }
    ])
  })

  it('parses quoted CSV fields containing LF, CRLF, commas, and escaped quotes', () => {
    expect(
      parseGlossary(
        '"AI\nML","人工智能,\r\n""机器学习"""\r\nAPP,应用程序',
        'csv'
      )
    ).toEqual([
      { original: 'AI\nML', standard: '人工智能,\r\n"机器学习"' },
      { original: 'APP', standard: '应用程序' }
    ])
  })

  it('ignores CSV comment text without parsing quotes or delimiters inside it', () => {
    expect(parseGlossary('# ignored "quote,tab\tarrow→\nAI,人工智能', 'csv')).toEqual([
      { original: 'AI', standard: '人工智能' }
    ])
  })

  it('reports the physical source line after a multiline CSV record', () => {
    expect(() =>
      parseGlossary('"AI\nML",人工智能\r\nmissing delimiter', 'csv')
    ).toThrowError(
      expect.objectContaining({
        code: 'invalid-glossary-line',
        line: 3
      })
    )
  })

  it('reports the physical line containing malformed text after a multiline quote', () => {
    expect(() =>
      parseGlossary('"AI\nML"x,人工智能', 'csv')
    ).toThrowError(
      expect.objectContaining({
        code: 'malformed-delimited-line',
        line: 2
      })
    )
  })

  it.each([
    { filename: 'terms.csv', format: 'csv' },
    { filename: 'terms.tsv', format: 'tsv' },
    { filename: 'terms.txt', format: 'txt' }
  ] as const)(
    'preserves the detected $format format with decoded content',
    async ({ filename, format }) => {
      const file = new File(['AI→ML,人工智能'], filename)

      await expect(readTerminologyFile(file)).resolves.toEqual({
        content: 'AI→ML,人工智能',
        format
      })
    }
  )

  it('parses and deduplicates banned words across CSV, TSV, and arrow separators', () => {
    expect(
      parseBannedWords('\ufeff# note\n最好,第一\n唯一\t顶级\n最好 → 首选')
    ).toEqual(['最好', '第一', '唯一', '顶级', '首选'])
  })

  it('does not collapse distinct glossary pairs containing control characters', () => {
    expect(parseGlossary('a\u0000b,c\na,b\u0000c')).toEqual([
      { original: 'a\u0000b', standard: 'c' },
      { original: 'a', standard: 'b\u0000c' }
    ])
  })

  it.each([
    {
      input: 'missing delimiter',
      code: 'invalid-glossary-line',
      message: '第 1 行'
    },
    {
      input: 'same,same',
      code: 'identical-glossary-values',
      message: '第 1 行'
    },
    {
      input: `${'a'.repeat(201)},标准`,
      code: 'term-too-long',
      message: '200'
    }
  ])('returns deterministic glossary validation errors', ({ input, code, message }) => {
    expect(() => parseGlossary(input)).toThrowError(
      expect.objectContaining({ code, message: expect.stringContaining(message) })
    )
  })

  it('rejects malformed quoted CSV deterministically', () => {
    for (const input of [
      '"AI,人工智能',
      '"AI",人工智能"',
      'AI,人工"智能'
    ]) {
      expect(() => parseGlossary(input)).toThrowError(
        expect.objectContaining({
          code: 'malformed-delimited-line',
          line: 1
        })
      )
    }
  })

  it('enforces byte and entry limits before returning imported data', () => {
    const tooLarge = '词'.repeat(MAX_TERMINOLOGY_IMPORT_BYTES)
    expect(() => parseBannedWords(tooLarge)).toThrowError(
      expect.objectContaining({ code: 'import-too-large' })
    )

    const tooMany = Array.from(
      { length: MAX_TERMINOLOGY_ENTRIES + 1 },
      (_, index) => `词${index}`
    ).join('\n')
    expect(() => parseBannedWords(tooMany)).toThrowError(
      expect.objectContaining({ code: 'too-many-entries' })
    )
  })

  it('exports a BOM-prefixed CSV example', () => {
    const sample = glossaryExampleCsv()

    expect(sample.startsWith('\ufeff')).toBe(true)
    expect(sample).toContain('# 原文写法,规范写法')
    expect(sample).toContain('AI,人工智能')
  })
})

describe('useTerminology', () => {
  it('accepts valid existing glossary state within the complete options bound', () => {
    const glossary = Array.from({ length: 300 }, (_, index) => ({
      original: `原文${index}`,
      standard: `规范${index}`
    }))

    const terminology = useTerminology({ glossary, bannedWords: [] })

    expect(terminology.glossary.value).toEqual(glossary)
  })

  it('deduplicates manual and imported values while preserving first-seen order', () => {
    const terminology = useTerminology({
      glossary: [{ original: 'AI', standard: '人工智能' }],
      bannedWords: ['最好']
    })

    expect(terminology.addGlossaryTerm(' AI ', ' 人工智能 ')).toBe(false)
    expect(terminology.importGlossary('APP,应用程序\nAI,人工智能')).toBe(1)
    expect(terminology.addBannedWord(' 最好 ')).toBe(false)
    expect(terminology.importBannedWords('第一,最好')).toBe(1)

    expect(terminology.glossary.value).toEqual([
      { original: 'AI', standard: '人工智能' },
      { original: 'APP', standard: '应用程序' }
    ])
    expect(terminology.bannedWords.value).toEqual(['最好', '第一'])
  })

  it('enforces the total limit when merging an import into existing state', () => {
    const terminology = useTerminology({
      glossary: [],
      bannedWords: Array.from(
        { length: MAX_TERMINOLOGY_ENTRIES },
        (_, index) => `已有${index}`
      )
    })

    expect(() => terminology.importBannedWords('新增')).toThrowError(
      expect.objectContaining({ code: 'too-many-entries' })
    )
    expect(terminology.bannedWords.value).toHaveLength(MAX_TERMINOLOGY_ENTRIES)
  })

  it('accepts an exact 64 KiB complete options snapshot and rejects one projected manual mutation', () => {
    const options = buildOptionsAtSerializedSize(
      MAX_VERIFICATION_OPTIONS_JSON_BYTES
    )
    const terminology = useTerminology(options)
    const before = [...terminology.bannedWords.value]

    expect(() => terminology.addBannedWord('z')).toThrowError(
      expect.objectContaining({
        code: 'options-too-large',
        message: '完整检查设置不能超过 64 KiB。'
      })
    )
    expect(terminology.bannedWords.value).toEqual(before)
  })

  it('validates set operations against the complete projected options without mutation', () => {
    const options = buildOptionsAtSerializedSize(
      MAX_VERIFICATION_OPTIONS_JSON_BYTES
    )
    const terminology = useTerminology({
      ...options,
      bannedWords: []
    })

    expect(() =>
      terminology.setBannedWords([...options.bannedWords, 'z'])
    ).toThrowError(
      expect.objectContaining({ code: 'options-too-large' })
    )
    expect(terminology.bannedWords.value).toEqual([])
  })

  it('keeps the first sequential import and rejects an over-limit second import transactionally', () => {
    const first = 'new'
    const options = buildOptionsAtSerializedSize(
      MAX_VERIFICATION_OPTIONS_JSON_BYTES - first.length - 3
    )
    const terminology = useTerminology(options)

    expect(terminology.importBannedWords(first, 'txt')).toBe(1)
    const afterFirst = [...terminology.bannedWords.value]
    expect(verificationOptionsBytes({
      ...options,
      bannedWords: afterFirst
    })).toBe(MAX_VERIFICATION_OPTIONS_JSON_BYTES)

    expect(() => terminology.importBannedWords('next', 'txt')).toThrowError(
      expect.objectContaining({ code: 'options-too-large' })
    )
    expect(terminology.bannedWords.value).toEqual(afterFirst)
  })

  it('rejects malformed multiline imports without changing existing state', () => {
    const terminology = useTerminology({
      scenario: 'technical',
      enableSecurity: false,
      enableSensitive: false,
      enableAdExtreme: true,
      glossary: [{ original: 'AI', standard: '人工智能' }],
      bannedWords: ['最好']
    })

    expect(() =>
      terminology.importGlossary('"APP\n应用程序', 'csv')
    ).toThrowError(
      expect.objectContaining({
        code: 'malformed-delimited-line',
        line: 1
      })
    )
    expect(terminology.glossary.value).toEqual([
      { original: 'AI', standard: '人工智能' }
    ])
    expect(terminology.bannedWords.value).toEqual(['最好'])
  })

  it('uses a typed validation error', () => {
    try {
      parseGlossary('invalid')
    } catch (error) {
      expect(error).toBeInstanceOf(TerminologyImportError)
      return
    }
    throw new Error('Expected parseGlossary to fail.')
  })
})
