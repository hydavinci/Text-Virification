<script setup lang="ts">
import { ref } from 'vue'
import { copyAnalyzeOptions, DEFAULT_OCR_LANGUAGE, DEFAULT_EXTENDED_RULES, OCR_LANGUAGES, SCENARIO_OPTIONS } from '../../api/analyzeOptions'

import {
  TerminologyImportError,
  validateVerificationOptionsSize
} from '../../composables/useTerminology'
import type { AnalyzeOptions } from '../../types/verification'

const scenarios = SCENARIO_OPTIONS

const props = defineProps<{
  options: AnalyzeOptions
  compact?: boolean
}>()

const emit = defineEmits<{
  'update:options': [options: AnalyzeOptions]
}>()
const errorMessage = ref<string | null>(null)

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
    <label class="scenario-field">
      <span>文档场景</span>
      <select class="ui-field" aria-label="文档场景" :value="options.scenario" @change="selectScenario">
        <option v-for="scenario in scenarios" :key="scenario.id" :value="scenario.id" :data-scenario="scenario.id">
          {{ scenario.name }}
        </option>
      </select>
    </label>

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
    <p class="ocr-note">默认关闭；开启后增加英文词典拼写与保守语法检查。长句建议仍按文档场景筛选，仅提示人工调整，不自动改写正文。</p>
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
