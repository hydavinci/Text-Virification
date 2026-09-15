<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { copyAnalyzeOptions, DEFAULT_OCR_LANGUAGE, DEFAULT_EXTENDED_RULES, OCR_LANGUAGES, SCENARIO_OPTIONS } from '../../api/analyzeOptions'
import { fetchScenarioCatalog, scenarioCatalogKey, type ScenarioProfile } from '../../api/scenarioCatalog'

import {
  TerminologyImportError,
  validateVerificationOptionsSize
} from '../../composables/useTerminology'
import type { AnalyzeOptions } from '../../types/verification'

const scenarios = SCENARIO_OPTIONS

const props = defineProps<{
  options: AnalyzeOptions
  compact?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:options': [options: AnalyzeOptions]
}>()
const errorMessage = ref<string | null>(null)
const profiles = ref<ScenarioProfile[]>([])
const catalogLoading = ref(true)
const catalogError = ref(false)
const selectedProfile = computed(() => profiles.value.find((profile) => profile.id === props.options.scenario))
const loadCatalog = inject(scenarioCatalogKey, (signal) => fetchScenarioCatalog(fetch, signal))
let catalogController: AbortController | undefined

async function refreshCatalog(): Promise<void> {
  catalogController?.abort()
  const controller = new AbortController()
  catalogController = controller
  catalogLoading.value = true
  catalogError.value = false
  try {
    const result = await loadCatalog(controller.signal)
    if (!controller.signal.aborted) profiles.value = result
  } catch {
    if (!controller.signal.aborted) catalogError.value = true
  } finally {
    if (!controller.signal.aborted) catalogLoading.value = false
  }
}

onMounted(refreshCatalog)
onBeforeUnmount(() => catalogController?.abort())

function updateOptions(patch: Partial<AnalyzeOptions>): void {
  const next = copyAnalyzeOptions(props.options, patch)

  try {
    validateVerificationOptionsSize(next)
    errorMessage.value = null
    emit('update:options', next)
  } catch (error) {
    errorMessage.value =
      error instanceof TerminologyImportError
        ? error.message
        : '检查设置处理失败。'
  }
}

function selectScenario(event: Event): void {
  if (!(event.target instanceof HTMLSelectElement)) return
  const value = event.target.value
  const scenario = scenarios.find((option) => option.id === value)
  if (scenario) updateOptions({ scenario: scenario.id })
}

function selectOcrLanguage(event: Event): void {
  if (!(event.target instanceof HTMLSelectElement)) return
  const value = event.target.value
  const language = OCR_LANGUAGES.find((language) => language === value)
  if (language) updateOptions({ ocrLanguage: language })
}
</script>

<template>
  <section class="settings-body" :class="{ compact }" aria-label="检查设置">
    <div class="scenario-header">
      <label class="scenario-field">
        <span v-if="!compact">文档场景</span>
        <select class="ui-field" aria-label="文档场景" :disabled="disabled" :value="options.scenario" @change="selectScenario">
          <option v-for="scenario in scenarios" :key="scenario.id" :value="scenario.id" :data-scenario="scenario.id">
            {{ scenario.name }}
          </option>
        </select>
      </label>
      <slot name="scenario-actions" />
    </div>

    <section class="scenario-rules" aria-label="场景规则" :aria-busy="catalogLoading">
      <p v-if="catalogLoading" role="status">正在读取服务端规则清单…</p>
      <p v-else-if="catalogError" role="status">
        规则清单加载失败，暂时无法确认规则包内容；场景选择和检查设置仍保留。
        <button type="button" aria-label="重试加载规则清单" :disabled="disabled" @click="refreshCatalog">重试</button>
      </p>
      <template v-else-if="selectedProfile">
        <p><strong>{{ selectedProfile.name }}规则包</strong></p>
        <p>{{ selectedProfile.description }}</p>
        <p v-if="compact && selectedProfile.rules.length" class="rule-highlights">
          {{ selectedProfile.rules.map((rule) => rule.name).join(' · ') }}
        </p>
        <details class="rule-details" :open="!compact">
          <summary>规则详情 · {{ selectedProfile.base_checks.length }} 项基础检查<span v-if="selectedProfile.rules.length">、{{ selectedProfile.rules.length }} 项专业检查</span></summary>
        <ul v-if="selectedProfile.rules.length" class="specialist-rules">
          <li v-for="rule in selectedProfile.rules" :key="rule.id">
            <strong>{{ rule.name }}</strong>
            <span>{{ rule.description }}</span>
            <span v-if="rule.requires_complete_structure">需完整文本（TXT/Markdown 或完整粘贴内容）；DOCX、PDF、OCR 等提取结果跳过此项。</span>
          </li>
        </ul>
        <details>
          <summary>本包基础检查（{{ selectedProfile.base_checks.length }}项）</summary>
          <p>{{ selectedProfile.base_checks.map((check) => check.name).join('、') }}</p>
        </details>
        <p v-if="options.enableExtendedRules">
          已启用扩展检查：{{ selectedProfile.extended_checks.map((check) => check.name).join('、') }}
        </p>
        <details>
          <summary>本包语义复核重点</summary>
          <p>{{ selectedProfile.semantic_guidance }}</p>
        </details>
        <p>专业建议仅供人工确认；自定义术语、禁用词和显式开启的安全检查不随场景切换取消。</p>
        </details>
      </template>
    </section>

    <template v-if="!compact">
    <h2>可选语义检查</h2>
    <label class="switch" for="enable-semantic-discovery">
      <span>发现规则未覆盖的语法与语义问题</span>
      <input
        id="enable-semantic-discovery"
        :checked="options.enableSemanticDiscovery ?? false"
        type="checkbox"
        aria-describedby="semantic-discovery-note"
        @change="updateOptions({
          enableSemanticDiscovery: ($event.target as HTMLInputElement).checked
        })"
      />
    </label>
    <p id="semantic-discovery-note" class="ocr-note">
      默认关闭；启用后将抽样的局部片段及相关术语发送至服务端配置并允许的模型服务，
      可能增加费用和等待时间。不是全文覆盖或合规检查；建议仅供人工确认，不自动修改正文。
      敏感文档请勿启用。服务不可用时保留本地结果并显示降级提示。
    </p>
    <h2>扩展检查</h2>
    <label class="switch" for="enable-extended-rules">
      <span>中英文间距、空行、长句及英文拼写与语法建议</span>
      <input
        id="enable-extended-rules"
        :checked="options.enableExtendedRules ?? DEFAULT_EXTENDED_RULES"
        type="checkbox"
        @change="updateOptions({
          enableExtendedRules: ($event.target as HTMLInputElement).checked
        })"
      />
    </label>
    <p class="ocr-note">默认关闭；开启后增加英文词典拼写与保守语法检查。仅执行当前规则包声明的扩展检查；长句建议仅供人工调整，不自动改写正文。</p>
    <h2>图片与扫描 PDF</h2>
    <label class="scenario-field">
      <span>OCR 识别语言</span>
      <select
        class="ui-field"
        aria-label="OCR 识别语言"
        :value="options.ocrLanguage ?? DEFAULT_OCR_LANGUAGE"
        @change="selectOcrLanguage"
      >
        <option value="zh">中英文（默认）</option>
        <option value="en">英文</option>
        <option value="ja">日文</option>
      </select>
    </label>
    <p class="ocr-note">用于识别图片中的文字；日文识别不包含日文纠错。图片导出为可编辑 Word，不覆盖原图。</p>
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
    </template>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
  </section>
</template>

<style scoped>
.settings-body {
  padding: 0 0 20px;
}
.settings-body.compact { padding: 0; }
.scenario-header { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; }
.scenario-header .scenario-field { justify-content: flex-start; }
.scenario-rules { margin-top: 12px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 12px; line-height: 1.7; color: var(--muted); }
.scenario-rules p { margin: 6px 0; }
.scenario-rules > p:first-child { margin-top: 0; }
.rule-details { margin-top: 6px; }
.rule-highlights { color: var(--text); }
.scenario-rules strong { color: var(--text); }
.scenario-rules summary { cursor: pointer; }
.specialist-rules { padding-left: 18px; margin: 8px 0; }
.specialist-rules li { margin: 8px 0; }
.specialist-rules span { display: block; }
.ocr-note { color: var(--muted); font-size: 12px; line-height: 1.7; }
.scenario-field { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; font-size: 13px; color: var(--text); }
.scenario-field select { min-width: 120px; max-width: 100%; }
.settings-body h2 {
  margin: 26px 0 12px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  font-size: 14px;
  font-weight: 600;
}
.switch {
  min-height: 44px;
  padding: 12px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--text);
  font-size: 13px;
}
.switch input {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  margin: 0;
  accent-color: var(--primary);
}
[role='alert'] {
  color: var(--danger);
  font-weight: 500;
}
</style>
