<script setup lang="ts">
import { computed } from 'vue'

import type { AnalyzeOptions } from '../../types/verification'
import SourceInputPanel from './SourceInputPanel.vue'
import VerificationSettings from './VerificationSettings.vue'

const props = defineProps<{
  options: AnalyzeOptions
  text: string
  busy: boolean
  error: string | null
  settingsOpen: boolean
  recoveredFile?: { name: string; size: number } | null
  recoverable?: boolean
}>()
const emit = defineEmits<{
  'update:options': [options: AnalyzeOptions]
  'update:text': [text: string]
  'open-settings': []
  'submit-file': [file: File]
  'submit-text': [text: string]
  'resume-job': []
  'clear-job': []
}>()
const enabledChecks = computed(() => [
  props.options.enableSecurity && '个人信息',
  props.options.enableSensitive && '敏感表述',
  props.options.enableAdExtreme && '广告极限词'
].filter(Boolean).join('、'))
</script>

<template>
  <main class="setup">
    <header class="setup-heading">
      <span class="product-label">文档预检工作区</span>
      <h1>让每一次交付，更准确。</h1>
      <p>上传文档或粘贴文本，检查错别字、表达与合规问题。</p>
    </header>
    <section class="input-card">
      <SourceInputPanel
        :text="text"
        :busy="busy"
        :server-error="error"
        :recovered-file="recoveredFile"
        :recoverable="recoverable"
        @update:text="emit('update:text', $event)"
        @submit-file="emit('submit-file', $event)"
        @submit-text="emit('submit-text', $event)"
        @resume-job="emit('resume-job')"
        @clear-job="emit('clear-job')"
      >
        <template #settings>
          <div class="setup-options">
            <div class="options-row">
              <fieldset class="scenario-control" :disabled="busy">
                <VerificationSettings
                  compact
                  :options="options"
                  @update:options="emit('update:options', $event)"
                />
              </fieldset>
              <button
                class="settings-trigger ui-button ui-button--quiet"
                type="button"
                data-open-settings
                aria-haspopup="dialog"
                :aria-expanded="settingsOpen"
                @click="emit('open-settings')"
              >
                检查设置 <span aria-hidden="true">↗</span>
              </button>
            </div>
            <p class="options-summary">
              {{ enabledChecks ? `已启用：${enabledChecks}检查` : '合规检查未启用' }}
              <span v-if="options.glossary.length"> · {{ options.glossary.length }} 个术语</span>
              <span v-if="options.bannedWords.length"> · {{ options.bannedWords.length }} 个禁用词</span>
              <span v-if="options.enableExtendedRules"> · 扩展检查</span>
              <span v-if="options.enableSemanticDiscovery"> · 云端语义发现</span>
              <span v-if="options.ocrLanguage === 'en'"> · 英文 OCR</span>
              <span v-if="options.ocrLanguage === 'ja'"> · 日文 OCR</span>
            </p>
          </div>
          <slot name="progress" />
        </template>
      </SourceInputPanel>
    </section>
    <p class="privacy-note">仅为完成检查处理文档 · 任务数据默认保留 24 小时 · 请勿上传涉密文件</p>
  </main>
</template>

<style scoped>
.setup { max-width: 800px; margin: 0 auto; padding: 24px 24px 20px; }
.setup-heading { margin-bottom: 18px; text-align: center; }
.product-label { display: inline-flex; align-items: center; gap: 8px; padding: 5px 12px; border-radius: 20px; background: var(--primary-soft); font-size: 12px; font-weight: 500; letter-spacing: .08em; color: var(--primary); }
.product-label::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
h1 { margin: 10px 0 8px; font-size: clamp(25px, 3vw, 32px); line-height: 1.35; font-weight: 600; letter-spacing: -.035em; }
.setup-heading p { margin: 0; color: var(--muted); font-size: 14px; line-height: 1.8; }
.input-card { padding: 20px; border: 1px solid var(--border); border-radius: 18px; background: var(--surface); box-shadow: var(--shadow-paper); }
.setup-options { min-width: 0; margin: 16px 0 0; padding: 14px 0 0; border: 0; border-top: 1px solid var(--border); }
.options-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.scenario-control { min-width: 0; margin: 0; padding: 0; border: 0; }
.settings-trigger { white-space: nowrap; }
.options-summary { margin: 12px 0 0; color: var(--muted); font-size: 12px; line-height: 1.8; }
.privacy-note { margin: 20px 0 0; color: var(--muted); text-align: center; font-size: 12px; line-height: 1.9; }
@media (max-width: 600px) {
  .setup { padding: 32px 16px 24px; }
  .input-card { padding: 18px; }
  .options-row { flex-wrap: wrap; }
}
</style>
