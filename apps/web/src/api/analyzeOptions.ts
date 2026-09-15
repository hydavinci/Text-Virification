import type {
  AnalyzeOptions,
  GlossaryTerm,
  Scenario
} from '../types/verification'
import { stripPythonWhitespace } from './pythonWhitespace'
import { hasLoneSurrogate } from './unicode'

export const SCENARIO_OPTIONS: readonly { id: Scenario; name: string }[] = [
  { id: 'general', name: '通用文档' },
  { id: 'academic', name: '学术论文' },
  { id: 'business', name: '商务文档' },
  { id: 'legal', name: '法律文书' },
  { id: 'news', name: '新闻稿' },
  { id: 'technical', name: '技术文档' }
]
export const SCENARIOS: readonly Scenario[] = SCENARIO_OPTIONS.map((option) => option.id)
export const OCR_LANGUAGES = ['zh', 'en', 'ja'] as const
export const DEFAULT_OCR_LANGUAGE = 'zh'
export const DEFAULT_EXTENDED_RULES = false
export const DEFAULT_SEMANTIC_DISCOVERY = false

export function createDefaultAnalyzeOptions(): AnalyzeOptions {
  return {
    scenario: 'general',
    enableSecurity: true,
    enableSensitive: true,
    enableAdExtreme: false,
    glossary: [],
    bannedWords: []
  }
}

export function copyAnalyzeOptions(options: AnalyzeOptions, patch: Partial<AnalyzeOptions> = {}): AnalyzeOptions {
  const merged = { ...options, ...patch }
  return {
    ...merged,
    glossary: merged.glossary.map((term) => ({ ...term })),
    bannedWords: [...merged.bannedWords]
  }
}
const MAX_TERMINOLOGY_ITEMS = 500
const MAX_TERMINOLOGY_CODE_POINTS = 200
const MAX_OPTIONS_JSON_BYTES = 64 * 1024

export class AnalyzeOptionsError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'AnalyzeOptionsError'
  }
}

export function createAnalyzeOptionsSnapshot(
  options: AnalyzeOptions,
  budget: 'request' | 'persisted' = 'request'
): AnalyzeOptions {
  if (
    typeof options !== 'object' ||
    options === null ||
    !SCENARIOS.includes(options.scenario) ||
    typeof options.enableSecurity !== 'boolean' ||
    typeof options.enableSensitive !== 'boolean' ||
    typeof options.enableAdExtreme !== 'boolean' ||
    (options.ocrLanguage !== undefined &&
      !OCR_LANGUAGES.includes(options.ocrLanguage)) ||
    (options.enableExtendedRules !== undefined &&
      typeof options.enableExtendedRules !== 'boolean') ||
    (options.enableSemanticDiscovery !== undefined &&
      typeof options.enableSemanticDiscovery !== 'boolean') ||
    !Array.isArray(options.glossary) ||
    !Array.isArray(options.bannedWords)
  ) {
    throw new AnalyzeOptionsError('Verification options are invalid.')
  }

  const glossary = options.glossary
    .map(cloneGlossaryTerm)
    .filter((term) => term.original !== term.standard)
  const bannedWords: string[] = []
  const seenBannedWords = new Set<string>()
  for (const word of options.bannedWords) {
    if (typeof word !== 'string') {
      throw invalidOptions()
    }
    const normalized = stripPythonWhitespace(word)
    if (!normalized || seenBannedWords.has(normalized)) {
      continue
    }
    if (
      hasLoneSurrogate(normalized) ||
      codePointLength(normalized) > MAX_TERMINOLOGY_CODE_POINTS
    ) {
      throw invalidOptions()
    }
    bannedWords.push(normalized)
    seenBannedWords.add(normalized)
  }
  if (
    glossary.length > MAX_TERMINOLOGY_ITEMS ||
    bannedWords.length > MAX_TERMINOLOGY_ITEMS
  ) {
    throw invalidOptions()
  }

  Object.freeze(glossary)
  Object.freeze(bannedWords)
  const snapshot = Object.freeze({
    scenario: options.scenario,
    enableSecurity: options.enableSecurity,
    enableSensitive: options.enableSensitive,
    enableAdExtreme: options.enableAdExtreme,
    ...(options.ocrLanguage === undefined ? {} : { ocrLanguage: options.ocrLanguage }),
    ...(options.enableExtendedRules === undefined ? {} : {
      enableExtendedRules: options.enableExtendedRules
    }),
    ...(options.enableSemanticDiscovery === undefined ? {} : {
      enableSemanticDiscovery: options.enableSemanticDiscovery
    }),
    glossary,
    bannedWords
  })
  if (serializedBackendBytes(snapshot, budget) > MAX_OPTIONS_JSON_BYTES) {
    throw invalidOptions()
  }
  return snapshot
}

export function appendAnalyzeOptions(
  body: FormData | URLSearchParams,
  options: AnalyzeOptions
): void {
  body.append('scenario', options.scenario)
  body.append('enable_security', String(options.enableSecurity))
  body.append('enable_sensitive', String(options.enableSensitive))
  body.append('enable_ad_extreme', String(options.enableAdExtreme))
  body.append('ocr_language', options.ocrLanguage ?? DEFAULT_OCR_LANGUAGE)
  body.append('enable_extended_rules', String(options.enableExtendedRules ?? DEFAULT_EXTENDED_RULES))
  body.append('enable_semantic_discovery', String(options.enableSemanticDiscovery ?? DEFAULT_SEMANTIC_DISCOVERY))
  body.append('custom_glossary', JSON.stringify(options.glossary))
  body.append('banned_words', JSON.stringify(options.bannedWords))
}

function cloneGlossaryTerm(term: GlossaryTerm): GlossaryTerm {
  if (
    typeof term !== 'object' ||
    term === null ||
    typeof term.original !== 'string' ||
    typeof term.standard !== 'string'
  ) {
    throw invalidOptions()
  }
  if (
    hasLoneSurrogate(term.original) ||
    hasLoneSurrogate(term.standard) ||
    codePointLength(term.original) < 1 ||
    codePointLength(term.original) > MAX_TERMINOLOGY_CODE_POINTS ||
    codePointLength(term.standard) > MAX_TERMINOLOGY_CODE_POINTS
  ) {
    throw invalidOptions()
  }
  return Object.freeze({
    original: term.original,
    standard: term.standard
  })
}

function codePointLength(value: string): number {
  return Array.from(value).length
}

function serializedBackendBytes(
  options: AnalyzeOptions,
  budget: 'request' | 'persisted'
): number {
  return new TextEncoder().encode(
    JSON.stringify({
      scenario: options.scenario,
      enable_security: options.enableSecurity,
      enable_sensitive: options.enableSensitive,
      enable_ad_extreme: options.enableAdExtreme,
      ...(budget === 'request' || options.ocrLanguage !== undefined
        ? { ocr_language: options.ocrLanguage ?? DEFAULT_OCR_LANGUAGE } : {}),
      ...(budget === 'request' || options.enableExtendedRules !== undefined
        ? { enable_extended_rules: options.enableExtendedRules ?? DEFAULT_EXTENDED_RULES } : {}),
      ...(budget === 'request' || options.enableSemanticDiscovery !== undefined
        ? { enable_semantic_discovery: options.enableSemanticDiscovery ?? DEFAULT_SEMANTIC_DISCOVERY } : {}),
      custom_glossary: options.glossary,
      banned_words: options.bannedWords
    })
  ).byteLength
}

function invalidOptions(): AnalyzeOptionsError {
  return new AnalyzeOptionsError('Verification options are invalid.')
}
