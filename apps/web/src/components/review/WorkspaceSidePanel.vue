<script setup lang="ts">
defineProps<{
  open: boolean
  title: string
}>()

const emit = defineEmits<{
  close: []
}>()
</script>

<template>
  <aside v-show="open" class="workspace-side-panel" :aria-label="title">
    <header class="workspace-side-panel__header">
      <h2 class="workspace-side-panel__title">{{ title }}</h2>
      <button
        type="button"
        class="workspace-side-panel__close"
        :aria-label="`关闭${title}面板`"
        @click="emit('close')"
      >
        ×
      </button>
    </header>

    <div class="workspace-side-panel__content">
      <slot />
    </div>
  </aside>
</template>

<style scoped>
.workspace-side-panel {
  display: grid;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: var(--review-panel-radius);
}

.workspace-side-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--review-space-3);
  padding: calc(var(--review-space-3) + 2px) var(--review-space-4);
  border-bottom: 1px solid var(--review-border);
}

.workspace-side-panel__title {
  margin: 0;
  color: var(--review-text);
  font-size: 0.92rem;
  line-height: 1.4;
}

.workspace-side-panel__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 44px;
  padding: 0;
  color: var(--review-text-muted);
  font: inherit;
  white-space: nowrap;
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 2px);
  cursor: pointer;
}

.workspace-side-panel__close:focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

.workspace-side-panel__content {
  min-height: 0;
  overflow: auto;
  padding: var(--review-space-4);
}
</style>
