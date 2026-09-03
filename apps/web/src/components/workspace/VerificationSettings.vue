<script setup lang="ts">
import type { AnalyzeOptions, Scenario } from '../../types/verification'

interface ScenarioOption {
  id: Scenario
  name: string
  description: string
  icon: string
}

const scenarios: ScenarioOption[] = [
  { id: 'general', name: '通用文档', description: '全面检查', icon: '通' },
  { id: 'academic', name: '学术论文', description: '术语与格式', icon: '学' },
  { id: 'business', name: '商务文档', description: '表达与规范', icon: '商' },
  { id: 'legal', name: '法律文书', description: '严谨与一致', icon: '法' },
  { id: 'news', name: '新闻稿', description: '准确与时效', icon: '新' },
  { id: 'technical', name: '技术文档', description: '术语与数字', icon: '技' }
]

const props = defineProps<{
  options: AnalyzeOptions
}>()

const emit = defineEmits<{
  'update:options': [options: AnalyzeOptions]
}>()

function updateOptions(patch: Partial<AnalyzeOptions>): void {
  emit('update:options', {
    ...props.options,
    ...patch,
    glossary: props.options.glossary.map((term) => ({ ...term })),
    bannedWords: [...props.options.bannedWords]
  })
}
</script>

<template>
  <section class="settings-body" aria-labelledby="verification-settings-heading">
    <h2 id="verification-settings-heading">文档场景</h2>
    <div class="scenario-grid">
      <button
        v-for="scenario in scenarios"
        :key="scenario.id"
        :class="{ active: options.scenario === scenario.id }"
        :aria-pressed="options.scenario === scenario.id"
        :data-scenario="scenario.id"
        type="button"
        @click="updateOptions({ scenario: scenario.id })"
      >
        <span aria-hidden="true">{{ scenario.icon }}</span>
        <strong>{{ scenario.name }}</strong>
        <small>{{ scenario.description }}</small>
      </button>
    </div>

    <h2>合规开关</h2>
    <label class="switch" for="enable-security">
      <span>个人信息与凭证扫描</span>
      <input
        id="enable-security"
        :checked="options.enableSecurity"
        type="checkbox"
        @change="updateOptions({
          enableSecurity: ($event.target as HTMLInputElement).checked
        })"
      />
    </label>
    <label class="switch" for="enable-sensitive">
      <span>政治与敏感表述检查</span>
      <input
        id="enable-sensitive"
        :checked="options.enableSensitive"
        type="checkbox"
        @change="updateOptions({
          enableSensitive: ($event.target as HTMLInputElement).checked
        })"
      />
    </label>
    <label class="switch" for="enable-ad-extreme">
      <span>广告法极限词检查</span>
      <input
        id="enable-ad-extreme"
        :checked="options.enableAdExtreme"
        type="checkbox"
        @change="updateOptions({
          enableAdExtreme: ($event.target as HTMLInputElement).checked
        })"
      />
    </label>
  </section>
</template>

<style scoped>
.settings-body {
  padding: 4px 20px 22px;
}
.settings-body h2 {
  margin: 18px 0 10px;
  font-size: 14px;
}
.scenario-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.scenario-grid button {
  padding: 12px 7px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 12px;
  color: inherit;
  background: var(--surface-2);
  cursor: pointer;
}
.scenario-grid button.active {
  color: var(--primary);
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, var(--surface));
}
.scenario-grid button:focus-visible {
  outline: 3px solid rgba(37, 99, 235, .14);
}
.scenario-grid strong {
  font-size: 12px;
}
.scenario-grid small {
  color: var(--muted);
  font-size: 10px;
}
.switch {
  padding: 10px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  font-size: 13px;
}
.switch input {
  width: 35px;
  height: 20px;
  accent-color: var(--primary);
}
@media (max-width: 680px) {
  .scenario-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
