<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { AnalyzeOptions } from '../../types/verification'
import AccessibleDialog from './AccessibleDialog.vue'
import SourceInputPanel from './SourceInputPanel.vue'
import TerminologyEditor from './TerminologyEditor.vue'
import VerificationSettings from './VerificationSettings.vue'

const props = defineProps<{
  options: AnalyzeOptions
  text: string
  busy: boolean
  error: string | null
  settingsTab: 'settings' | 'terms' | 'banned'
}>()
const emit = defineEmits<{
  'update:options': [options: AnalyzeOptions]
  'update:text': [text: string]
  'update:settingsTab': [tab: 'settings' | 'terms' | 'banned']
  'submit-file': [file: File]
  'submit-text': [text: string]
  notify: [message: string]
}>()
const settingsOpen = ref(false)
const enabledChecks = computed(() => [
  props.options.enableSecurity && '个人信息',
  props.options.enableSensitive && '敏感表述',
  props.options.enableAdExtreme && '广告极限词'
].filter(Boolean).join('、'))

watch(() => props.busy, (busy) => {
  if (busy) settingsOpen.value = false
})
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
        @update:text="emit('update:text', $event)"
        @submit-file="emit('submit-file', $event)"
        @submit-text="emit('submit-text', $event)"
      >
        <template #settings>
          <fieldset class="setup-options" :disabled="busy">
            <div class="options-row">
              <VerificationSettings
                compact
                :options="options"
                @update:options="emit('update:options', $event)"
              />
              <button
                class="settings-trigger"
                type="button"
                data-open-settings
                aria-haspopup="dialog"
                :aria-expanded="settingsOpen"
                @click="settingsOpen = true"
              >
                检查设置 <span aria-hidden="true">↗</span>
              </button>
            </div>
            <p class="options-summary">
              {{ enabledChecks ? `已启用：${enabledChecks}检查` : '合规检查未启用' }}
              <span v-if="options.glossary.length"> · {{ options.glossary.length }} 个术语</span>
              <span v-if="options.bannedWords.length"> · {{ options.bannedWords.length }} 个禁用词</span>
              <span v-if="options.enableExtendedRules"> · 扩展检查</span>
              <span v-if="options.ocrLanguage === 'en'"> · 英文 OCR</span>
              <span v-if="options.ocrLanguage === 'ja'"> · 日文 OCR</span>
            </p>
          </fieldset>
        </template>
      </SourceInputPanel>
      <slot name="progress" />
    </section>
    <p class="privacy-note">仅为完成检查处理文档 · 任务数据默认保留 24 小时 · 请勿上传涉密文件</p>

    <AccessibleDialog
      :open="settingsOpen"
      drawer
      labelled-by="settings-title"
      close-label="关闭检查设置"
      close-data-attribute="data-close-settings"
      @close="settingsOpen = false"
    >
      <h2 id="settings-title">检查设置</h2>
      <p class="settings-intro">按文档需要调整，修改会用于下一次检查。</p>
      <div class="side-tabs" aria-label="设置分类">
        <button type="button" :class="{ active: settingsTab === 'settings' }" :aria-pressed="settingsTab === 'settings'" @click="emit('update:settingsTab', 'settings')">检查项</button>
        <button type="button" :class="{ active: settingsTab === 'terms' }" :aria-pressed="settingsTab === 'terms'" @click="emit('update:settingsTab', 'terms')">术语 {{ options.glossary.length }}</button>
        <button type="button" :class="{ active: settingsTab === 'banned' }" :aria-pressed="settingsTab === 'banned'" @click="emit('update:settingsTab', 'banned')">禁用词 {{ options.bannedWords.length }}</button>
      </div>
      <VerificationSettings
        v-if="settingsTab === 'settings'"
        :options="options"
        @update:options="emit('update:options', $event)"
      />
      <TerminologyEditor
        v-else
        :kind="settingsTab === 'terms' ? 'glossary' : 'banned'"
        :options="options"
        @update:options="emit('update:options', $event)"
        @notify="emit('notify', $event)"
      />
    </AccessibleDialog>
  </main>
</template>

<style scoped>
.setup { max-width: 760px; margin: 0 auto; padding: 56px 24px 32px; }
.setup-heading { margin-bottom: 30px; text-align: center; }
.product-label { font-size: 11px; font-weight: 500; letter-spacing: .12em; color: var(--muted); }
h1 { margin: 14px 0 12px; font-size: clamp(25px, 3vw, 32px); font-weight: 600; letter-spacing: -.035em; }
.setup-heading p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.8; }
.input-card { padding: 28px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); box-shadow: 0 2px 8px rgba(15, 23, 42, .025); }
.setup-options { min-width: 0; margin: 22px 0 0; padding: 0; border: 0; }
.options-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.settings-trigger { display: flex; align-items: center; gap: 8px; padding: 8px 0 8px 8px; border: 0; color: var(--muted); background: transparent; font-size: 12px; cursor: pointer; white-space: nowrap; }
.settings-trigger:hover { color: var(--primary); }
.options-summary { margin: 12px 0 0; color: var(--muted); font-size: 11px; line-height: 1.8; }
.privacy-note { margin: 18px 0 0; color: var(--muted); text-align: center; font-size: 11px; line-height: 1.9; }
h2 { font-size: 19px; font-weight: 600; }
.settings-intro { margin-bottom: 24px; font-size: 12px; }
.side-tabs { display: flex; gap: 4px; padding: 4px; margin-bottom: 20px; border-radius: 8px; background: var(--surface-2); }
.side-tabs button { flex: 1; padding: 9px 8px; border: 0; border-radius: 6px; background: transparent; color: var(--muted); cursor: pointer; font-size: 12px; }
.side-tabs button.active { color: var(--text); background: var(--surface); box-shadow: 0 1px 3px rgba(0,0,0,.06); }
@media (max-width: 600px) {
  .setup { padding: 32px 16px 24px; }
  .input-card { padding: 18px; }
  .options-row { flex-wrap: wrap; }
}
</style>
