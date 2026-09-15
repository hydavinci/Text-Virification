<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

defineProps<{
  trackChanges: boolean
  reportDisabled: boolean
  modifiedDisabled: boolean
  recheckDisabled: boolean
  busy: boolean
  blockedReason?: string | null
}>()

defineEmits<{
  recheck: []
  'export-report': []
  'export-modified': []
  'update:trackChanges': [value: boolean]
}>()

const expanded = ref(false)
const panel = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)

function closeOptions(): void {
  expanded.value = false
  trigger.value?.focus()
}

function dismissOutside(event: PointerEvent): void {
  if (event.target instanceof Node && !panel.value?.contains(event.target)) {
    expanded.value = false
  }
}

function dismissOnBlur(event: FocusEvent): void {
  if (event.relatedTarget instanceof Node && !panel.value?.contains(event.relatedTarget)) {
    expanded.value = false
  }
}

onMounted(() => document.addEventListener('pointerdown', dismissOutside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', dismissOutside))
</script>

<template>
  <div ref="panel" class="export-panel" aria-label="导出操作" @focusout="dismissOnBlur">
    <button
      class="btn ui-button ui-button--quiet"
      type="button"
      data-action="recheck"
      :disabled="recheckDisabled || busy"
      @click="$emit('recheck')"
    >
      重新检查
    </button>
    <div class="export-disclosure">
      <button
        ref="trigger"
        class="btn ui-button ui-button--quiet"
        type="button"
        data-toggle-export
        :aria-expanded="expanded"
        @click="expanded = !expanded"
        @keydown.esc.prevent="closeOptions"
      >
        {{ busy ? '正在导出…' : '导出' }} <span aria-hidden="true">⌄</span>
      </button>
      <div
        v-show="expanded"
        class="export-options"
        data-export-options
        role="group"
        aria-label="导出选项"
        @keydown.esc.prevent.stop="closeOptions"
      >
    <button
      class="btn ghost ui-button"
      type="button"
      data-action="export-report"
      :disabled="reportDisabled || busy"
      @click="$emit('export-report')"
    >
      检查报告
    </button>
    <button
      class="btn ghost ui-button"
      type="button"
      data-action="export-modified"
      :disabled="modifiedDisabled || busy"
      @click="$emit('export-modified')"
    >
      {{ busy ? '正在导出…' : '导出修改文件' }}
    </button>
    <label class="switch compact">
      <input
        data-track-changes
        type="checkbox"
        :disabled="busy"
        :checked="trackChanges"
        aria-label="导出时保留修订标记"
        @change="
          $emit(
            'update:trackChanges',
            ($event.target as HTMLInputElement).checked
          )
        "
      />
      <span>保留修订</span>
    </label>
      </div>
    </div>
    <small v-if="blockedReason" class="blocked-reason" role="status" aria-live="polite">
      {{ blockedReason }}
    </small>
  </div>
</template>

<style scoped>
.export-panel {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}
.switch {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px;
  color: var(--muted);
  font-size: 13px;
}
.switch input {
  width: 16px;
  height: 16px;
  accent-color: var(--primary);
}
.blocked-reason {
  max-width: 22rem;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.export-panel { flex-wrap: wrap; font-size: 12px; }
.export-disclosure { position: relative; }
.export-options { position: absolute; right: 0; top: calc(100% + 2px); z-index: 30; width: 220px; padding: 8px; display: flex; flex-direction: column; gap: 4px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); }
.export-options .btn { justify-content: flex-start; border: 0; padding: 11px; box-shadow: none; }
.export-options .btn:hover:not(:disabled) { background: var(--surface-2); }
.export-options .switch { padding: 12px 8px 8px; border-top: 1px solid var(--border); }
@media (max-width: 760px) {
  .export-panel {
    flex-wrap: wrap;
    justify-content: flex-end;
  }
}
</style>
