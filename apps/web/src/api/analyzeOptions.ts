import type {
  AnalyzeOptions,
  GlossaryTerm,
  Scenario
} from '../types/verification'

const SCENARIOS: readonly Scenario[] = [
  'general',
  'academic',
  'business',
  'legal',
  'news',
  'technical'
]

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

  const glossary = options.glossary.map(cloneGlossaryTerm)
  const bannedWords = options.bannedWords.map((word) => {
    if (typeof word !== 'string') {
      throw new AnalyzeOptionsError('Verification options are invalid.')
    }
    return word
  })

  Object.freeze(glossary)
  Object.freeze(bannedWords)
  return Object.freeze({
    scenario: options.scenario,
    enableSecurity: options.enableSecurity,
    enableSensitive: options.enableSensitive,
    enableAdExtreme: options.enableAdExtreme,
    glossary,
    bannedWords
  })
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
    throw new AnalyzeOptionsError('Verification options are invalid.')
  }
  return Object.freeze({
    original: term.original,
    standard: term.standard
  })
}
