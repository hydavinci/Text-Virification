<script setup lang="ts">
defineProps<{
  visible: boolean
  conflict: string | null
  canUndo: boolean
  busy: boolean
}>()

const emit = defineEmits<{
  undo: []
}>()
</script>

<template>
  <div
    v-if="visible || conflict"
    class="undo-toast"
    data-testid="undo-toast"
    role="status"
    aria-live="polite"
  >
    <span>{{ conflict ?? '处理已保存，可撤销最近操作。' }}</span>
    <button
      type="button"
      name="undo-latest"
      :disabled="busy || !canUndo"
      @click="emit('undo')"
    >
      撤销
    </button>
  </div>
</template>

<style scoped>
.undo-toast {
  position: absolute;
  right: var(--review-space-4);
  bottom: var(--review-space-4);
  z-index: 6;
  display: inline-flex;
  align-items: center;
  gap: var(--review-space-3);
  max-width: min(420px, calc(100% - 32px));
  padding: 10px 12px;
  color: var(--review-text);
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: var(--review-panel-radius);
  box-shadow: 0 18px 42px rgba(22, 31, 52, 0.16);
}

.undo-toast span {
  min-width: 0;
  font-size: 0.8rem;
  line-height: 1.45;
}

.undo-toast button {
  min-height: 44px;
  padding: 8px 11px;
  color: var(--review-accent);
  font-weight: 800;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 1px solid transparent;
  border-radius: calc(var(--review-panel-radius) - 4px);
  cursor: pointer;
}

.undo-toast button:focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

.undo-toast button:disabled {
  color: #8c93a8;
  cursor: not-allowed;
  background: var(--review-canvas);
}
</style>
