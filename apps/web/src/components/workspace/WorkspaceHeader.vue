<script setup lang="ts">
defineProps<{
  theme: 'light' | 'dark'
  hasResult: boolean
  settingsOpen?: boolean
}>()

defineEmits<{
  reset: []
  'open-settings': []
  'open-privacy': []
  'open-help': []
  'toggle-theme': []
}>()
</script>

<template>
  <header class="topbar">
    <button
      class="brand"
      type="button"
      data-reset-workspace
      aria-label="返回新建检查并清空当前工作区"
      @click="$emit('reset')"
    >
      <span class="brand-mark" aria-hidden="true">啄</span>
      <span>
        <strong>啄木鸟</strong>
        <small>中英文字智能检查</small>
      </span>
    </button>
    <div class="top-actions">
      <button
        v-if="hasResult"
        class="settings-btn ui-button"
        type="button"
        data-open-settings
        aria-haspopup="dialog"
        :aria-expanded="settingsOpen ?? false"
        @click="$emit('open-settings')"
      >
        检查设置
      </button>
      <slot v-if="hasResult" name="exports"></slot>
      <div class="utility-actions">
      <button
        class="icon-btn"
        type="button"
        data-open-privacy
        aria-label="打开隐私说明"
        title="隐私说明"
        @click="$emit('open-privacy')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" /><path d="m8 12 3 3 5-6" /></svg>
      </button>
      <button
        class="icon-btn"
        type="button"
        data-open-help
        aria-label="打开使用帮助"
        title="使用帮助"
        @click="$emit('open-help')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 1 1 4.1 2c-1.1.6-1.6 1-1.6 2.5M12 16v1" /></svg>
      </button>
      <button
        class="icon-btn"
        type="button"
        data-toggle-theme
        :aria-label="theme === 'light' ? '切换到深色主题' : '切换到浅色主题'"
        :title="theme === 'light' ? '切换到深色主题' : '切换到浅色主题'"
        @click="$emit('toggle-theme')"
      >
        <svg v-if="theme === 'light'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M20.5 13.5A8.5 8.5 0 0 1 10.5 3 8.5 8.5 0 1 0 20.5 13.5Z" /></svg>
        <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></svg>
      </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  min-height: 60px;
  padding: 8px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.brand {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  border: 0;
  background: none;
  cursor: pointer;
  text-align: left;
}
.brand-mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: var(--on-primary);
  font-weight: 600;
  background: var(--primary);
  box-shadow: var(--shadow-small);
}
.brand strong,
.brand small {
  display: block;
}
.brand strong {
  font-size: 15px;
  letter-spacing: .04em;
}
.brand small {
  margin-top: 1px;
  color: var(--muted);
  font-size: 12px;
}
.top-actions {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}
.utility-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  padding-left: 8px;
  border-left: 1px solid var(--border);
}
.icon-btn {
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  border: 0;
  border-radius: var(--radius-control);
  background: var(--surface);
  cursor: pointer;
}
.settings-btn {
  white-space: nowrap;
}
.icon-btn { display: grid; place-items: center; color: var(--muted); }
.icon-btn svg { width: 18px; height: 18px; }
.icon-btn:hover { background: var(--surface-2); color: var(--text); }
@media (max-width: 760px) {
  .topbar {
    padding: 8px 13px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    gap: 8px;
  }
  .brand { grid-column: 1; grid-row: 1; justify-self: start; }
  .top-actions { display: contents; }
  .utility-actions { grid-column: 2 / -1; grid-row: 1; justify-self: end; border: 0; padding: 0; }
  .settings-btn { grid-column: 1; grid-row: 2; justify-self: end; }
  .top-actions > :deep(.export-panel) { display: contents; }
  .top-actions :deep(.export-panel > [data-action='recheck']) { grid-column: 2; grid-row: 2; }
  .top-actions :deep(.export-disclosure) { grid-column: 3; grid-row: 2; }
  .top-actions :deep(.blocked-reason) { grid-column: 1 / -1; grid-row: 3; justify-self: end; max-width: 100%; }
}
@media (max-width: 420px) {
  .brand small {
    display: none;
  }
}
</style>
