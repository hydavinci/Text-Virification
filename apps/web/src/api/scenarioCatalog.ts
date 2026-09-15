import type { InjectionKey } from 'vue'
import type { Scenario } from '../types/verification'
import { SCENARIOS } from './analyzeOptions'
import { ApiResponseValidationError, readApiRequestError } from './errors'

interface CheckLabel {
  id: string
  name: string
}

export interface ScenarioRule extends CheckLabel {
  description: string
  requires_complete_structure: boolean
  manual_only: true
}

export interface ScenarioProfile {
  id: Scenario
  name: string
  description: string
  version: string
  base_checks: CheckLabel[]
  extended_checks: CheckLabel[]
  rules: ScenarioRule[]
  semantic_guidance: string
}

export const scenarioCatalogKey: InjectionKey<(signal: AbortSignal) => Promise<ScenarioProfile[]>> =
  Symbol('scenarioCatalog')

function invalidCatalog(): never {
  throw new ApiResponseValidationError('服务端规则清单无效，请刷新或联系管理员。')
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return invalidCatalog()
  return value as Record<string, unknown>
}

function text(value: unknown, limit = 2000): string {
  if (typeof value !== 'string' || !value.trim() || value.length > limit) return invalidCatalog()
  return value
}

function entries(value: unknown, limit = 100): unknown[] {
  if (!Array.isArray(value) || value.length > limit) return invalidCatalog()
  return value
}

function labels(value: unknown): CheckLabel[] {
  return entries(value).map((entry) => {
    const item = record(entry)
    return { id: text(item.id, 100), name: text(item.name, 100) }
  })
}

export async function fetchScenarioCatalog(
  fetchImpl: typeof fetch = fetch,
  signal?: AbortSignal
): Promise<ScenarioProfile[]> {
  const response = await fetchImpl('/api/v1/scenarios', { signal })
  if (!response.ok) throw await readApiRequestError(response)
  const payload: unknown = await response.json()
  const profiles = entries(record(payload).scenarios, SCENARIOS.length).map((entry) => {
    const item = record(entry)
    const id = SCENARIOS.find((scenario) => scenario === item.id)
    if (!id) return invalidCatalog()
    const rules = entries(item.rules).map((entry): ScenarioRule => {
      const rule = record(entry)
      const ruleId = text(rule.id, 100)
      if (!ruleId.startsWith(`scenario.${id}.`) ||
          typeof rule.requires_complete_structure !== 'boolean' || rule.manual_only !== true) {
        return invalidCatalog()
      }
      return {
        id: ruleId,
        name: text(rule.name, 100),
        description: text(rule.description),
        requires_complete_structure: rule.requires_complete_structure,
        manual_only: true
      }
    })
    if (new Set(rules.map((rule) => rule.id)).size !== rules.length) return invalidCatalog()
    return {
      id,
      name: text(item.name, 100),
      description: text(item.description),
      version: text(item.version, 100),
      base_checks: labels(item.base_checks),
      extended_checks: labels(item.extended_checks),
      rules,
      semantic_guidance: text(item.semantic_guidance, 4000)
    }
  })
  if (new Set(profiles.map((profile) => profile.id)).size !== SCENARIOS.length) return invalidCatalog()
  return profiles
}
