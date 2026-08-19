<script setup lang="ts">
import { CHECK_CATEGORY_VALUES, CHECK_SCENARIO_VALUES, type CheckCategory, type CheckScenario } from '../types/review'

const CATEGORY_LABELS: Record<CheckCategory, string> = {
  character: '字符规范',
  vocabulary: '词汇用法',
  sentence: '句法结构',
  format: '格式排版',
  discourse: '篇章逻辑',
  security: '安全合规'
}

const SCENARIO_LABELS: Record<CheckScenario, string> = {
  general: '通用',
  academic: '学术',
  business: '商务',
  legal: '法律',
  news: '新闻',
  technical: '技术'
}

const props = defineProps<{
  scenario: CheckScenario
  enabledCategories: CheckCategory[]
  busy?: boolean
}>()

const emit = defineEmits<{
  'update:scenario': [scenario: CheckScenario]
  'update:enabledCategories': [enabledCategories: CheckCategory[]]
}>()

function handleScenarioChange(event: Event) {
  emit('update:scenario', (event.target as HTMLSelectElement).value as CheckScenario)
}

function handleCategoryChange(category: CheckCategory, event: Event) {
  const input = event.target as HTMLInputElement
  const nextCategories = new Set(props.enabledCategories)

  if (input.checked) {
    nextCategories.add(category)
  } else {
    nextCategories.delete(category)
  }

  emit(
    'update:enabledCategories',
    CHECK_CATEGORY_VALUES.filter((value) => nextCategories.has(value))
  )
}

function isCategoryEnabled(category: CheckCategory) {
  return props.enabledCategories.includes(category)
}
</script>

<template>
  <section class="check-options" aria-labelledby="check-options-title">
    <div class="check-options__header">
      <div>
        <h3 id="check-options-title">核验配置</h3>
        <p>上传前确认场景与检查范围</p>
      </div>
      <p class="check-options__note">共享规则由管理员维护</p>
    </div>

    <div class="check-options__layout">
      <label class="check-options__field" for="scenario">
        <span>核验场景</span>
        <select
          id="scenario"
          name="scenario"
          :value="scenario"
          :disabled="busy"
          @change="handleScenarioChange"
        >
          <option v-for="value in CHECK_SCENARIO_VALUES" :key="value" :value="value">
            {{ SCENARIO_LABELS[value] }}
          </option>
        </select>
      </label>

      <fieldset class="check-options__categories" :disabled="busy">
        <legend>检查类别</legend>
        <div class="check-options__category-grid">
          <label
            v-for="category in CHECK_CATEGORY_VALUES"
            :key="category"
            class="check-options__category"
            :for="`category-${category}`"
          >
            <input
              :id="`category-${category}`"
              :name="`category-${category}`"
              type="checkbox"
              :checked="isCategoryEnabled(category)"
              @change="handleCategoryChange(category, $event)"
            />
            <span>{{ CATEGORY_LABELS[category] }}</span>
          </label>
        </div>
      </fieldset>
    </div>
  </section>
</template>

<style scoped>
.check-options {
  margin-bottom: 24px;
  padding: 22px 24px;
  background: #f8f9ff;
  border: 1px solid #dbe2f5;
  border-radius: 18px;
}

.check-options__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}

h3 {
  margin: 0;
  color: #20283a;
  font-size: 0.96rem;
}

.check-options__header p,
.check-options__note {
  margin: 6px 0 0;
  color: #667085;
  font-size: 0.8rem;
}

.check-options__note {
  margin-top: 0;
  white-space: nowrap;
}

.check-options__layout {
  display: grid;
  gap: 18px;
}

.check-options__field {
  display: grid;
  gap: 9px;
  color: #30394d;
  font-size: 0.86rem;
  font-weight: 600;
}

.check-options__field select {
  width: 100%;
  min-height: 44px;
  padding: 0 13px;
  color: #20283a;
  font: inherit;
  font-weight: 500;
  background: #fff;
  border: 1px solid #cfd6ef;
  border-radius: 12px;
}

.check-options__field select:focus-visible,
.check-options__category:focus-within {
  outline: 3px solid rgba(91, 111, 242, 0.25);
  outline-offset: 3px;
}

.check-options__categories {
  min-width: 0;
  padding: 0;
  margin: 0;
  border: 0;
}

.check-options__categories legend {
  padding: 0;
  color: #30394d;
  font-size: 0.86rem;
  font-weight: 600;
}

.check-options__category-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-top: 10px;
}

.check-options__category {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 12px 14px;
  color: #30394d;
  font-size: 0.84rem;
  font-weight: 500;
  cursor: pointer;
  background: #fff;
  border: 1px solid #dbe2f5;
  border-radius: 12px;
}

.check-options__category input {
  margin: 0;
}

.check-options__field select:disabled,
.check-options__categories:disabled .check-options__category {
  cursor: not-allowed;
  opacity: 0.72;
}

@media (max-width: 560px) {
  .check-options {
    padding: 20px;
  }

  .check-options__header {
    flex-direction: column;
  }

  .check-options__note {
    white-space: normal;
  }
}
</style>
