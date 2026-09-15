import { SCENARIO_OPTIONS } from '../../src/api/analyzeOptions'

export function scenarioCatalogFixture() {
  return SCENARIO_OPTIONS.map((option) => ({
    ...option,
    version: '1',
    description: `${option.name}的独立规则`,
    base_checks: [{ id: 'punctuation', name: '标点使用' }],
    extended_checks: [{ id: 'extended_english', name: '扩展英文检查' }],
    rules: option.id === 'general' ? [] : [{
      id: `scenario.${option.id}.example`,
      name: `${option.name}专用检查`,
      description: `只按${option.name}的明确证据检查`,
      requires_complete_structure: option.id === 'academic',
      manual_only: true as const
    }],
    semantic_guidance: `${option.name}的语义审阅重点`
  }))
}
