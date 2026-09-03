import type {
  AnalyzeOptions,
  GlossaryTerm,
  Scenario
} from '../types/verification'
import { stripPythonWhitespace } from './pythonWhitespace'
import { hasLoneSurrogate } from './unicode'

const SCENARIOS: readonly Scenario[] = [
  'general',
  'academic',
  'business',
  'legal',
  'news',
  'technical'
]
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
  options: AnalyzeOptions
): AnalyzeOptions {
  if (
    typeof options !== 'object' ||
    options === null ||
    !SCENARIOS.includes(options.scenario) ||
    typeof options.enableSecurity !== 'boolean' ||
    typeof options.enableSensitive !== 'boolean' ||
    typeof options.enableAdExtreme !== 'boolean' ||
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
    glossary,
    bannedWords
  })
  if (serializedBackendBytes(snapshot) > MAX_OPTIONS_JSON_BYTES) {
    throw invalidOptions()
  }
  return snapshot
}

export function appendAnalyzeOptions(
  body: FormData,
  options: AnalyzeOptions
): void {
  body.append('scenario', options.scenario)
  body.append('enable_security', String(options.enableSecurity))
  body.append('enable_sensitive', String(options.enableSensitive))
  body.append('enable_ad_extreme', String(options.enableAdExtreme))
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

function serializedBackendBytes(options: AnalyzeOptions): number {
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

function invalidOptions(): AnalyzeOptionsError {
  return new AnalyzeOptionsError('Verification options are invalid.')
}
