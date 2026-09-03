<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  text: string
  previewText: string
}>()

const emit = defineEmits<{
  save: [text: string]
}>()

const editing = ref(false)
const previewing = ref(false)
const draft = ref(props.text)
const status = ref('')
const editor = ref<HTMLTextAreaElement | null>(null)
const startButton = ref<HTMLButtonElement | null>(null)

async function startEdit(): Promise<void> {
  draft.value = props.text
  status.value = ''
  previewing.value = false
  editing.value = true
  await nextTick()
  editor.value?.focus()
}

async function finishEditing(): Promise<void> {
  editing.value = false
  await nextTick()
  startButton.value?.focus()
}

async function cancelEdit(): Promise<void> {
  draft.value = props.text
  status.value = '已取消编辑'
  await finishEditing()
}

async function saveEdit(): Promise<void> {
  if (draft.value.trim().length === 0) {
    status.value = '内容不能为空'
    await nextTick()
    editor.value?.focus()
    return
  }
  if (draft.value === props.text) {
    status.value = '内容未发生变化'
    await finishEditing()
    return
  }
  emit('save', draft.value)
  status.value = '编辑已保存，需要重新检查'
  await finishEditing()
}

function togglePreview(): void {
  previewing.value = !previewing.value
  status.value = previewing.value ? '正在显示修改预览' : ''
}

watch(
  () => props.text,
  (text) => {
    if (!editing.value) {
      draft.value = text
    }
  }
)
</script>

<template>
  <div class="edit-preview">
    <div class="edit-actions" aria-label="文档编辑和预览">
      <button
        v-if="!editing"
        ref="startButton"
        type="button"
        data-action="start-edit"
        @click="startEdit"
      >
        编辑原文
      </button>
      <button
        v-if="editing"
        class="accept"
        type="button"
        data-action="save-edit"
        @click="saveEdit"
      >
        保存编辑
      </button>
      <button
        v-if="editing"
        class="reject"
        type="button"
        data-action="cancel-edit"
        @click="cancelEdit"
      >
        取消编辑
      </button>
      <button
        v-if="!editing"
        type="button"
        data-action="toggle-preview"
        :aria-pressed="previewing"
        @click="togglePreview"
      >
        {{ previewing ? '返回文档' : '修改预览' }}
      </button>
      <span
        data-edit-status
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {{ status }}
      </span>
    </div>

    <textarea
      v-if="editing"
      ref="editor"
      v-model="draft"
      class="document-editor"
      data-edit-input
      aria-label="编辑文档内容"
    />
    <pre
      v-else-if="previewing"
      class="document-content preview"
      data-preview-content
    >{{ previewText }}</pre>
    <div v-else class="document-content">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.edit-preview {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

.edit-actions {
  min-height: 45px;
  padding: 7px 12px;
  display: flex;
  align-items: center;
  gap: 7px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
}

button {
  padding: 7px 11px;
  border: 1px solid var(--border);
  border-radius: 9px;
  color: var(--text);
  background: var(--surface);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
}

button.accept {
  color: #15803d;
  background: #dcfce7;
}

button.reject {
  color: #be123c;
  background: #fff1f2;
}

button:focus-visible,
textarea:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--primary) 35%, transparent);
  outline-offset: 2px;
}

[data-edit-status] {
  color: var(--muted);
  font-size: 11px;
}

.document-content,
.document-editor {
  flex: 1;
  min-height: 0;
  width: 100%;
  margin: 0;
  padding: 24px 28px;
  overflow: auto;
  border: 0;
  border-radius: 0;
  resize: none;
  white-space: pre-wrap;
  color: var(--text);
  background: var(--surface);
  font: 15px/2 ui-monospace, SFMono-Regular, Menlo, monospace;
}

.document-content:has(> :deep(.document-viewer)) {
  padding: 0;
}

.preview {
  color: #075985;
}
</style>
