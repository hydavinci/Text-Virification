import { readonly, ref } from 'vue'

import type { GlossaryTerm } from '../types/verification'

export const MAX_TERMINOLOGY_IMPORT_BYTES = 64 * 1024
export const MAX_TERMINOLOGY_ENTRIES = 500
export const MAX_TERMINOLOGY_VALUE_LENGTH = 200

export type TerminologyImportFormat = 'auto' | 'csv' | 'tsv' | 'txt'
export type TerminologyImportErrorCode =
  | 'import-too-large'
  | 'too-many-entries'
  | 'invalid-glossary-line'
  | 'malformed-delimited-line'
  | 'empty-value'
  | 'term-too-long'
  | 'identical-glossary-values'
  | 'unsupported-file-type'

export class TerminologyImportError extends Error {
  constructor(
    public readonly code: TerminologyImportErrorCode,
    message: string,
    public readonly line: number | null = null
  ) {
    super(message)
    this.name = 'TerminologyImportError'
  }
}

interface TerminologyState {
  glossary: readonly GlossaryTerm[]
  bannedWords: readonly string[]
}

function importError(
  code: TerminologyImportErrorCode,
  message: string,
  line: number | null = null
): never {
  throw new TerminologyImportError(code, message, line)
}

function validateImportBytes(value: string): void {
  if (new TextEncoder().encode(value).byteLength > MAX_TERMINOLOGY_IMPORT_BYTES) {
    importError(
      'import-too-large',
      `导入内容不能超过 ${MAX_TERMINOLOGY_IMPORT_BYTES / 1024} KiB。`
    )
  }
}

function validateValue(value: string, line: number, label: string): string {
  const normalized = value.trim()
  if (!normalized) {
    importError('empty-value', `第 ${line} 行的${label}不能为空。`, line)
  }
  if (Array.from(normalized).length > MAX_TERMINOLOGY_VALUE_LENGTH) {
    importError(
      'term-too-long',
      `第 ${line} 行的${label}不能超过 ${MAX_TERMINOLOGY_VALUE_LENGTH} 个字符。`,
      line
    )
  }
  return normalized
}

function nonCommentLines(value: string): Array<{ line: number; value: string }> {
  const normalized = value.replace(/^\ufeff/, '')
  return normalized
    .split(/\r\n?|\n/)
    .map((line, index) => ({ line: index + 1, value: line.trim() }))
    .filter(({ value: line }) => line !== '' && !line.startsWith('#'))
}

function delimitersFor(format: TerminologyImportFormat): readonly string[] {
  if (format === 'csv') {
    return [',']
  }
  if (format === 'tsv') {
    return ['\t']
  }
  return ['\t', '→', ',']
}

function findDelimiter(
  value: string,
  format: TerminologyImportFormat,
  line: number
): string | null {
  const candidates = delimitersFor(format)
  let inQuotes = false
  const found = new Set<string>()

  for (let index = 0; index < value.length; index += 1) {
    if (value[index] === '"') {
      if (inQuotes && value[index + 1] === '"') {
        index += 1
      } else {
        inQuotes = !inQuotes
      }
      continue
    }
    if (!inQuotes) {
      const delimiter = candidates.find((candidate) =>
        value.startsWith(candidate, index)
      )
      if (delimiter) {
        found.add(delimiter)
      }
    }
  }

  if (inQuotes) {
    importError(
      'malformed-delimited-line',
      `第 ${line} 行包含未闭合的引号。`,
      line
    )
  }
  return candidates.find((candidate) => found.has(candidate)) ?? null
}

function parseDelimitedLine(
  value: string,
  delimiter: string,
  line: number
): string[] {
  const fields: string[] = []
  let field = ''
  let inQuotes = false
  let closedQuote = false

  for (let index = 0; index < value.length; index += 1) {
    const character = value[index]
    if (inQuotes) {
      if (character === '"') {
        if (value[index + 1] === '"') {
          field += '"'
          index += 1
        } else {
          inQuotes = false
          closedQuote = true
        }
      } else {
        field += character
      }
      continue
    }

    if (value.startsWith(delimiter, index)) {
      fields.push(field.trim())
      field = ''
      closedQuote = false
      index += delimiter.length - 1
      continue
    }
    if (character === '"') {
      if (field.trim() === '' && !closedQuote) {
        field = ''
        inQuotes = true
        continue
      }
      importError(
        'malformed-delimited-line',
        `第 ${line} 行的引号字段格式无效。`,
        line
      )
    }
    if (closedQuote && !/\s/.test(character)) {
      importError(
        'malformed-delimited-line',
        `第 ${line} 行的引号字段格式无效。`,
        line
      )
    }
    field += character
  }

  if (inQuotes) {
    importError(
      'malformed-delimited-line',
      `第 ${line} 行包含未闭合的引号。`,
      line
    )
  }
  fields.push(field.trim())
  return fields
}

function assertEntryLimit(length: number): void {
  if (length > MAX_TERMINOLOGY_ENTRIES) {
    importError(
      'too-many-entries',
      `术语或禁用词最多允许 ${MAX_TERMINOLOGY_ENTRIES} 项。`
    )
  }
}

function glossaryKey(term: GlossaryTerm): string {
  return JSON.stringify([term.original, term.standard])
}

function normalizeGlossaryTerms(terms: readonly GlossaryTerm[]): GlossaryTerm[] {
  const normalized: GlossaryTerm[] = []
  const seen = new Set<string>()

  for (const [index, term] of terms.entries()) {
    const line = index + 1
    const original = validateValue(term.original, line, '原文写法')
    const standard = validateValue(term.standard, line, '规范写法')
    if (original === standard) {
      importError(
        'identical-glossary-values',
        `第 ${line} 行的原文写法和规范写法必须不同。`,
        line
      )
    }
    const normalizedTerm = { original, standard }
    const key = glossaryKey(normalizedTerm)
    if (!seen.has(key)) {
      normalized.push(normalizedTerm)
      seen.add(key)
      assertEntryLimit(normalized.length)
    }
  }

  return normalized
}

export function parseGlossary(
  value: string,
  format: TerminologyImportFormat = 'auto'
): GlossaryTerm[] {
  validateImportBytes(value)
  const terms: GlossaryTerm[] = []
  const seen = new Set<string>()

  for (const entry of nonCommentLines(value)) {
    const delimiter = findDelimiter(entry.value, format, entry.line)
    if (!delimiter) {
      importError(
        'invalid-glossary-line',
        `第 ${entry.line} 行必须包含逗号、制表符或 → 分隔的两个字段。`,
        entry.line
      )
    }
    const fields = parseDelimitedLine(entry.value, delimiter, entry.line)
    if (fields.length !== 2) {
      importError(
        'invalid-glossary-line',
        `第 ${entry.line} 行必须且只能包含两个字段。`,
        entry.line
      )
    }
    const original = validateValue(fields[0] ?? '', entry.line, '原文写法')
    const standard = validateValue(fields[1] ?? '', entry.line, '规范写法')
    if (original === standard) {
      importError(
        'identical-glossary-values',
        `第 ${entry.line} 行的原文写法和规范写法必须不同。`,
        entry.line
      )
    }
    const term = { original, standard }
    const key = glossaryKey(term)
    if (!seen.has(key)) {
      terms.push(term)
      seen.add(key)
      assertEntryLimit(terms.length)
    }
  }
  return terms
}

export function parseBannedWords(
  value: string,
  format: TerminologyImportFormat = 'auto'
): string[] {
  validateImportBytes(value)
  const words: string[] = []
  const seen = new Set<string>()

  for (const entry of nonCommentLines(value)) {
    const delimiter = findDelimiter(entry.value, format, entry.line)
    const fields = delimiter
      ? parseDelimitedLine(entry.value, delimiter, entry.line)
      : [entry.value]
    for (const field of fields) {
      if (!field.trim()) {
        continue
      }
      const word = validateValue(field, entry.line, '禁用词')
      if (!seen.has(word)) {
        words.push(word)
        seen.add(word)
        assertEntryLimit(words.length)
      }
    }
  }
  return words
}

export async function readTerminologyFile(file: File): Promise<string> {
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (!extension || !['csv', 'tsv', 'txt'].includes(extension)) {
    importError(
      'unsupported-file-type',
      '仅支持 CSV、TSV 或 TXT 导入文件。'
    )
  }
  if (file.size > MAX_TERMINOLOGY_IMPORT_BYTES) {
    importError(
      'import-too-large',
      `导入文件不能超过 ${MAX_TERMINOLOGY_IMPORT_BYTES / 1024} KiB。`
    )
  }

  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () =>
      reject(
        new TerminologyImportError(
          'malformed-delimited-line',
          '无法读取导入文件。'
        )
      )
    reader.readAsText(file, 'UTF-8')
  })
}

export function glossaryExampleCsv(): string {
  return '\ufeff# 原文写法,规范写法\nAI,人工智能\nAPP,应用程序\n'
}

export function bannedWordsExampleTxt(): string {
  return '\ufeff# 每行一个禁用词，也可使用逗号或制表符分隔\n最好\n第一\n'
}

export function useTerminology(initial: TerminologyState = {
  glossary: [],
  bannedWords: []
}) {
  const glossary = ref<GlossaryTerm[]>([])
  const bannedWords = ref<string[]>([])

  function setGlossary(terms: readonly GlossaryTerm[]): void {
    glossary.value = normalizeGlossaryTerms(terms)
  }

  function setBannedWords(words: readonly string[]): void {
    const normalized: string[] = []
    const seen = new Set<string>()
    for (const [index, value] of words.entries()) {
      const word = validateValue(value, index + 1, '禁用词')
      if (!seen.has(word)) {
        normalized.push(word)
        seen.add(word)
        assertEntryLimit(normalized.length)
      }
    }
    bannedWords.value = normalized
  }

  function addGlossaryTerm(originalValue: string, standardValue: string): boolean {
    const original = validateValue(originalValue, 1, '原文写法')
    const standard = validateValue(standardValue, 1, '规范写法')
    if (original === standard) {
      importError(
        'identical-glossary-values',
        '原文写法和规范写法必须不同。'
      )
    }
    const term = { original, standard }
    if (glossary.value.some((item) => glossaryKey(item) === glossaryKey(term))) {
      return false
    }
    assertEntryLimit(glossary.value.length + 1)
    glossary.value = [...glossary.value, term]
    return true
  }

  function addBannedWord(value: string): boolean {
    const word = validateValue(value, 1, '禁用词')
    if (bannedWords.value.includes(word)) {
      return false
    }
    assertEntryLimit(bannedWords.value.length + 1)
    bannedWords.value = [...bannedWords.value, word]
    return true
  }

  function importGlossary(
    value: string,
    format: TerminologyImportFormat = 'auto'
  ): number {
    const imported = parseGlossary(value, format)
    const next = [...glossary.value]
    const seen = new Set(next.map(glossaryKey))
    let added = 0
    for (const term of imported) {
      const key = glossaryKey(term)
      if (!seen.has(key)) {
        next.push(term)
        seen.add(key)
        added += 1
      }
    }
    assertEntryLimit(next.length)
    glossary.value = next
    return added
  }

  function importBannedWords(
    value: string,
    format: TerminologyImportFormat = 'auto'
  ): number {
    const imported = parseBannedWords(value, format)
    const next = [...bannedWords.value]
    const seen = new Set(next)
    let added = 0
    for (const word of imported) {
      if (!seen.has(word)) {
        next.push(word)
        seen.add(word)
        added += 1
      }
    }
    assertEntryLimit(next.length)
    bannedWords.value = next
    return added
  }

  function removeGlossaryTerm(index: number): void {
    glossary.value = glossary.value.filter((_, current) => current !== index)
  }

  function removeBannedWord(index: number): void {
    bannedWords.value = bannedWords.value.filter((_, current) => current !== index)
  }

  function clearGlossary(): void {
    glossary.value = []
  }

  function clearBannedWords(): void {
    bannedWords.value = []
  }

  setGlossary(initial.glossary)
  setBannedWords(initial.bannedWords)

  return {
    glossary: readonly(glossary),
    bannedWords: readonly(bannedWords),
    setGlossary,
    setBannedWords,
    addGlossaryTerm,
    addBannedWord,
    importGlossary,
    importBannedWords,
    removeGlossaryTerm,
    removeBannedWord,
    clearGlossary,
    clearBannedWords
  }
}
