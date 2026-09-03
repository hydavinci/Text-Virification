import { readonly, ref } from 'vue'

import {
  isPythonWhitespace,
  stripPythonWhitespace
} from '../api/pythonWhitespace'
import { hasLoneSurrogate } from '../api/unicode'
import type { AnalyzeOptions, GlossaryTerm } from '../types/verification'

export const MAX_TERMINOLOGY_IMPORT_BYTES = 64 * 1024
export const MAX_TERMINOLOGY_ENTRIES = 500
export const MAX_TERMINOLOGY_VALUE_LENGTH = 200
export const MAX_VERIFICATION_OPTIONS_JSON_BYTES = 64 * 1024

export type TerminologyImportFormat = 'auto' | 'csv' | 'tsv' | 'txt'
export type DetectedTerminologyImportFormat = Exclude<
  TerminologyImportFormat,
  'auto'
>
export type TerminologyImportErrorCode =
  | 'import-too-large'
  | 'options-too-large'
  | 'too-many-entries'
  | 'invalid-glossary-line'
  | 'malformed-delimited-line'
  | 'empty-value'
  | 'term-too-long'
  | 'invalid-unicode'
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

type TerminologyState = Pick<AnalyzeOptions, 'glossary' | 'bannedWords'> &
  Partial<
    Pick<
      AnalyzeOptions,
      'scenario' | 'enableSecurity' | 'enableSensitive' | 'enableAdExtreme'
    >
  >

export interface ReadTerminologyFileResult {
  content: string
  format: DetectedTerminologyImportFormat
}

function importError(
  code: TerminologyImportErrorCode,
  message: string,
  line: number | null = null
): never {
  throw new TerminologyImportError(code, message, line)
}

function validateImportBytes(value: string): void {
  assertValidUnicode(value)
  if (new TextEncoder().encode(value).byteLength > MAX_TERMINOLOGY_IMPORT_BYTES) {
    importError(
      'import-too-large',
      `导入内容不能超过 ${MAX_TERMINOLOGY_IMPORT_BYTES / 1024} KiB。`
    )
  }
}

export function verificationOptionsJsonBytes(options: AnalyzeOptions): number {
  for (const [index, term] of options.glossary.entries()) {
    assertValidUnicode(term.original, index + 1, '原文写法')
    assertValidUnicode(term.standard, index + 1, '规范写法')
  }
  for (const [index, word] of options.bannedWords.entries()) {
    assertValidUnicode(word, index + 1, '禁用词')
  }
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

export function validateVerificationOptionsSize(
  options: AnalyzeOptions
): void {
  if (
    verificationOptionsJsonBytes(options) >
    MAX_VERIFICATION_OPTIONS_JSON_BYTES
  ) {
    importError(
      'options-too-large',
      `完整检查设置不能超过 ${MAX_VERIFICATION_OPTIONS_JSON_BYTES / 1024} KiB。`
    )
  }
}

function validateValue(value: string, line: number, label: string): string {
  const normalized = stripPythonWhitespace(value)
  assertValidUnicode(normalized, line, label)
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

function assertValidUnicode(
  value: string,
  line: number | null = null,
  label = '文本'
): void {
  if (!hasLoneSurrogate(value)) {
    return
  }
  importError(
    'invalid-unicode',
    line === null
      ? '文本包含无效的 Unicode 代理项。'
      : `第 ${line} 行的${label}包含无效的 Unicode 代理项。`,
    line
  )
}

function nonCommentLines(value: string): Array<{ line: number; value: string }> {
  const normalized = value.replace(/^\ufeff/, '')
  return normalized
    .split(/\r\n?|\n/)
    .map((line, index) => ({
      line: index + 1,
      value: stripPythonWhitespace(line)
    }))
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
      fields.push(stripPythonWhitespace(field))
      field = ''
      closedQuote = false
      index += delimiter.length - 1
      continue
    }
    if (character === '"') {
      if (stripPythonWhitespace(field) === '' && !closedQuote) {
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
    if (closedQuote && !isPythonWhitespace(character)) {
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
  fields.push(stripPythonWhitespace(field))
  return fields
}

interface ParsedDelimitedRecord {
  line: number
  fields: string[]
}

function parseDelimitedRecords(
  value: string,
  delimiter: string
): ParsedDelimitedRecord[] {
  const normalized = value.replace(/^\ufeff/, '')
  const records: ParsedDelimitedRecord[] = []
  let fields: string[] = []
  let field = ''
  let recordText = ''
  let inQuotes = false
  let inComment = false
  let closedQuote = false
  let line = 1
  let recordLine = 1
  let quoteLine = 1

  const finishRecord = () => {
    const source = stripPythonWhitespace(recordText)
    if (source && !source.startsWith('#')) {
      records.push({
        line: recordLine,
        fields: [...fields, stripPythonWhitespace(field)]
      })
    }
    fields = []
    field = ''
    recordText = ''
    inComment = false
    closedQuote = false
  }

  for (let index = 0; index < normalized.length; index += 1) {
    const character = normalized[index] ?? ''
    const isCrLf =
      character === '\r' && normalized[index + 1] === '\n'
    if (character === '\r' || character === '\n') {
      if (inQuotes) {
        const newline = isCrLf ? '\r\n' : character
        field += newline
        recordText += newline
      } else {
        finishRecord()
      }
      if (isCrLf) {
        index += 1
      }
      line += 1
      if (!inQuotes) {
        recordLine = line
      }
      continue
    }

    if (
      !inQuotes &&
      !inComment &&
      fields.length === 0 &&
      stripPythonWhitespace(field) === '' &&
      stripPythonWhitespace(recordText) === '' &&
      character === '#'
    ) {
      inComment = true
    }
    recordText += character
    if (inComment) {
      continue
    }
    if (inQuotes) {
      if (character === '"') {
        if (normalized[index + 1] === '"') {
          field += '"'
          recordText += '"'
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

    if (normalized.startsWith(delimiter, index)) {
      fields.push(stripPythonWhitespace(field))
      field = ''
      closedQuote = false
      index += delimiter.length - 1
      continue
    }
    if (character === '"') {
      if (stripPythonWhitespace(field) === '' && !closedQuote) {
        field = ''
        inQuotes = true
        quoteLine = line
        continue
      }
      importError(
        'malformed-delimited-line',
        `第 ${line} 行的引号字段格式无效。`,
        line
      )
    }
    if (closedQuote && !isPythonWhitespace(character)) {
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
      `第 ${quoteLine} 行包含未闭合的引号。`,
      quoteLine
    )
  }
  finishRecord()
  return records
}

function parsedRecords(
  value: string,
  format: TerminologyImportFormat
): ParsedDelimitedRecord[] {
  if (format === 'csv') {
    return parseDelimitedRecords(value, ',')
  }
  if (format === 'tsv') {
    return parseDelimitedRecords(value, '\t')
  }
  return nonCommentLines(value).map((entry) => {
    const delimiter = findDelimiter(entry.value, format, entry.line)
    return {
      line: entry.line,
      fields: delimiter
        ? parseDelimitedLine(entry.value, delimiter, entry.line)
        : [entry.value]
    }
  })
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

  for (const entry of parsedRecords(value, format)) {
    if (entry.fields.length === 1) {
      importError(
        'invalid-glossary-line',
        `第 ${entry.line} 行必须包含逗号、制表符或 → 分隔的两个字段。`,
        entry.line
      )
    }
    if (entry.fields.length !== 2) {
      importError(
        'invalid-glossary-line',
        `第 ${entry.line} 行必须且只能包含两个字段。`,
        entry.line
      )
    }
    const original = validateValue(
      entry.fields[0] ?? '',
      entry.line,
      '原文写法'
    )
    const standard = validateValue(
      entry.fields[1] ?? '',
      entry.line,
      '规范写法'
    )
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

  for (const entry of parsedRecords(value, format)) {
    for (const field of entry.fields) {
      if (!stripPythonWhitespace(field)) {
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

export async function readTerminologyFile(
  file: File
): Promise<ReadTerminologyFileResult> {
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

  const content = await new Promise<string>((resolve, reject) => {
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
  return {
    content,
    format: extension as DetectedTerminologyImportFormat
  }
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
  const initialOptions: AnalyzeOptions = {
    scenario: initial.scenario ?? 'general',
    enableSecurity: initial.enableSecurity ?? true,
    enableSensitive: initial.enableSensitive ?? true,
    enableAdExtreme: initial.enableAdExtreme ?? false,
    glossary: initial.glossary.map((term) => ({ ...term })),
    bannedWords: [...initial.bannedWords]
  }
  const scenario = ref(initialOptions.scenario)
  const enableSecurity = ref(initialOptions.enableSecurity)
  const enableSensitive = ref(initialOptions.enableSensitive)
  const enableAdExtreme = ref(initialOptions.enableAdExtreme)
  const glossary = ref<GlossaryTerm[]>([])
  const bannedWords = ref<string[]>([])

  function projectedOptions(
    nextGlossary: readonly GlossaryTerm[],
    nextBannedWords: readonly string[]
  ): AnalyzeOptions {
    return {
      scenario: scenario.value,
      enableSecurity: enableSecurity.value,
      enableSensitive: enableSensitive.value,
      enableAdExtreme: enableAdExtreme.value,
      glossary: nextGlossary.map((term) => ({ ...term })),
      bannedWords: [...nextBannedWords]
    }
  }

  function setOptions(options: AnalyzeOptions): void {
    const nextGlossary = normalizeGlossaryTerms(options.glossary)
    const nextBannedWords = normalizeBannedWords(options.bannedWords)
    validateVerificationOptionsSize({
      ...options,
      glossary: nextGlossary,
      bannedWords: nextBannedWords
    })
    scenario.value = options.scenario
    enableSecurity.value = options.enableSecurity
    enableSensitive.value = options.enableSensitive
    enableAdExtreme.value = options.enableAdExtreme
    glossary.value = nextGlossary
    bannedWords.value = nextBannedWords
  }

  function setGlossary(terms: readonly GlossaryTerm[]): void {
    const next = normalizeGlossaryTerms(terms)
    validateVerificationOptionsSize(projectedOptions(next, bannedWords.value))
    glossary.value = next
  }

  function setBannedWords(words: readonly string[]): void {
    const next = normalizeBannedWords(words)
    validateVerificationOptionsSize(projectedOptions(glossary.value, next))
    bannedWords.value = next
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
    const next = [...glossary.value, term]
    validateVerificationOptionsSize(projectedOptions(next, bannedWords.value))
    glossary.value = next
    return true
  }

  function addBannedWord(value: string): boolean {
    const word = validateValue(value, 1, '禁用词')
    if (bannedWords.value.includes(word)) {
      return false
    }
    assertEntryLimit(bannedWords.value.length + 1)
    const next = [...bannedWords.value, word]
    validateVerificationOptionsSize(projectedOptions(glossary.value, next))
    bannedWords.value = next
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
    validateVerificationOptionsSize(projectedOptions(next, bannedWords.value))
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
    validateVerificationOptionsSize(projectedOptions(glossary.value, next))
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

  function normalizeBannedWords(words: readonly string[]): string[] {
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
    return normalized
  }

  setOptions(initialOptions)

  return {
    glossary: readonly(glossary),
    bannedWords: readonly(bannedWords),
    setOptions,
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
