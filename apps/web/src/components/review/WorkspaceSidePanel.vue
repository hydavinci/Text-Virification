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
  background: #fff;
  border: 1px solid #dfe4f4;
  border-radius: 14px;
}

.workspace-side-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid #edf0f5;
}

.workspace-side-panel__title {
  margin: 0;
  color: #243154;
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
  color: #667085;
  font: inherit;
  background: #f8f9fc;
  border: 1px solid #dfe4ee;
  border-radius: 10px;
  cursor: pointer;
}

.workspace-side-panel__close:focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

.workspace-side-panel__content {
  min-height: 0;
  overflow: auto;
  padding: 16px;
}
</style>
