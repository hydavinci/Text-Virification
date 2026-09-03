<script setup lang="ts">
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
</script>

<template>
  <div class="export-panel" aria-label="导出操作">
    <button
      class="btn ghost"
      type="button"
      data-action="recheck"
      :disabled="recheckDisabled || busy"
      @click="$emit('recheck')"
    >
      重新检查
    </button>
    <button
      class="btn ghost"
      type="button"
      data-action="export-report"
      :disabled="reportDisabled || busy"
      @click="$emit('export-report')"
    >
      检查报告
    </button>
    <button
      class="btn primary"
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
.btn {
  border: 1px solid transparent;
  border-radius: 11px;
  padding: 9px 15px;
  color: inherit;
  background: var(--surface);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}
.btn:disabled {
  opacity: .55;
  cursor: not-allowed;
}
.btn.primary {
  color: white;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  box-shadow: 0 7px 18px rgba(37, 99, 235, .2);
}
.btn.ghost {
  border-color: var(--border);
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
  width: 35px;
  height: 20px;
  accent-color: var(--primary);
}
.blocked-reason {
  max-width: 18rem;
  color: var(--muted);
  line-height: 1.3;
}
@media (max-width: 760px) {
  .export-panel {
    width: 100%;
    flex-wrap: wrap;
    justify-content: flex-start;
  }
}
</style>
