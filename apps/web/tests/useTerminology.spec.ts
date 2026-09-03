import { describe, expect, it } from 'vitest'

import {
  MAX_TERMINOLOGY_ENTRIES,
  MAX_TERMINOLOGY_IMPORT_BYTES,
  TerminologyImportError,
  glossaryExampleCsv,
  parseBannedWords,
  parseGlossary,
  useTerminology
} from '../src/composables/useTerminology'

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
  it('accepts valid existing glossary state larger than one import file', () => {
    const glossary = Array.from({ length: MAX_TERMINOLOGY_ENTRIES }, (_, index) => ({
      original: `原文${index}${'甲'.repeat(70)}`,
      standard: `规范${index}${'乙'.repeat(70)}`
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
