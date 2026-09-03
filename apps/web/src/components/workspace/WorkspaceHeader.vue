<script setup lang="ts">
defineProps<{
  theme: 'light' | 'dark'
  hasResult: boolean
}>()

defineEmits<{
  reset: []
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
      <slot v-if="hasResult" name="exports"></slot>
      <button
        class="icon-btn"
        type="button"
        data-open-privacy
        aria-label="打开隐私说明"
        title="隐私说明"
        @click="$emit('open-privacy')"
      >
        隐
      </button>
      <button
        class="icon-btn"
        type="button"
        data-open-help
        aria-label="打开使用帮助"
        title="使用帮助"
        @click="$emit('open-help')"
      >
        ?
      </button>
      <button
        class="icon-btn"
        type="button"
        data-toggle-theme
        :aria-label="theme === 'light' ? '切换到深色主题' : '切换到浅色主题'"
        :title="theme === 'light' ? '切换到深色主题' : '切换到浅色主题'"
        @click="$emit('toggle-theme')"
      >
        {{ theme === 'light' ? '☾' : '☀' }}
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  min-height: 68px;
  padding: 8px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  backdrop-filter: blur(18px);
}
.brand {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 11px;
  border: 0;
  background: none;
  cursor: pointer;
  text-align: left;
}
.brand-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 13px;
  color: white;
  font-weight: 900;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  box-shadow: 0 8px 20px rgba(37, 99, 235, .28);
}
.brand strong,
.brand small {
  display: block;
}
.brand strong {
  font-size: 16px;
}
.brand small {
  margin-top: 1px;
  color: var(--muted);
  font-size: 11px;
}
.top-actions {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}
.icon-btn {
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: var(--surface);
  cursor: pointer;
}
@media (max-width: 760px) {
  .topbar {
    padding: 8px 13px;
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .top-actions {
    flex: 1 1 100%;
    flex-wrap: wrap;
    justify-content: flex-start;
  }
}
@media (max-width: 420px) {
  .brand small {
    display: none;
  }
}
</style>
