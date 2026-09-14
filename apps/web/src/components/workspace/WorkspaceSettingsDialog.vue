<script setup lang="ts">
import type { AnalyzeOptions } from '../../types/verification'
import AccessibleDialog from './AccessibleDialog.vue'
import TerminologyEditor from './TerminologyEditor.vue'
import VerificationSettings from './VerificationSettings.vue'

const props = defineProps<{
  open: boolean
  options: AnalyzeOptions
  busy: boolean
  hasResult: boolean
  settingsTab: 'settings' | 'terms' | 'banned'
}>()
const emit = defineEmits<{
  close: []
  'update:options': [options: AnalyzeOptions]
  'update:settingsTab': [tab: 'settings' | 'terms' | 'banned']
  notify: [message: string]
}>()

function updateOptions(options: AnalyzeOptions): void {
  if (props.busy) {
    emit('notify', '检查进行中，暂时不能修改设置')
    return
  }
  emit('update:options', options)
}
</script>

<template>
  <AccessibleDialog
    :open="open"
    drawer
    labelled-by="settings-title"
    close-label="关闭检查设置"
    close-data-attribute="data-close-settings"
    @close="emit('close')"
  >
    <h2 id="settings-title">检查设置</h2>
    <p v-if="busy" class="settings-intro" role="status">
      检查进行中，可查看设置，完成后可修改。
    </p>
    <p v-else class="settings-intro">
      {{ hasResult
        ? '修改不会清空当前文档和审阅记录；关闭设置后点击“重新检查”应用新设置。'
        : '按文档需要调整，修改会用于下一次检查。' }}
    </p>
    <p v-if="hasResult" class="settings-intro">
      重新检查使用当前修订文字，不重新识别图片；更换 OCR 语言后需重新上传文件。
    </p>
    <div class="side-tabs ui-tabs" aria-label="设置分类">
      <button type="button" :class="{ active: settingsTab === 'settings' }" :aria-pressed="settingsTab === 'settings'" @click="emit('update:settingsTab', 'settings')">检查项</button>
      <button type="button" :class="{ active: settingsTab === 'terms' }" :aria-pressed="settingsTab === 'terms'" @click="emit('update:settingsTab', 'terms')">术语 {{ options.glossary.length }}</button>
      <button type="button" :class="{ active: settingsTab === 'banned' }" :aria-pressed="settingsTab === 'banned'" @click="emit('update:settingsTab', 'banned')">禁用词 {{ options.bannedWords.length }}</button>
    </div>
    <fieldset class="settings-fields" :disabled="busy" aria-label="检查设置内容">
      <VerificationSettings
        v-if="settingsTab === 'settings'"
        :options="options"
        @update:options="updateOptions"
      />
      <TerminologyEditor
        v-else
        :kind="settingsTab === 'terms' ? 'glossary' : 'banned'"
        :options="options"
        @update:options="updateOptions"
        @notify="emit('notify', $event)"
      />
    </fieldset>
  </AccessibleDialog>
</template>

<style scoped>
h2 { margin-bottom: 12px; font-size: 20px; font-weight: 600; letter-spacing: -.02em; }
.settings-intro { margin: 0 0 16px; font-size: 13px; }
.settings-fields { min-width: 0; margin: 0; padding: 0; border: 0; }
.side-tabs { margin: 24px 0; }
.side-tabs button { flex: 1; padding-inline: 6px; }
</style>
