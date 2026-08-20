<script setup lang="ts">
import { computed, ref, type ComponentPublicInstance } from 'vue'

import type { WorkspaceTool } from './workspaceLayout'

const props = defineProps<{
  mode: 'rail' | 'bottom'
  activeTool: WorkspaceTool
  sidePanelOpen: boolean
  exportOpen: boolean
}>()

const emit = defineEmits<{
  activate: [tool: WorkspaceTool]
  toggleExport: []
}>()

type ToolItem = {
  id: WorkspaceTool
  label: string
  icon: string
}

const toolItems: ToolItem[] = [
  { id: 'document', label: '文档', icon: 'M6 4.5h8l4 4V19.5H6z M14 4.5V8.5h4' },
  { id: 'issues', label: '问题', icon: 'M7 6.5h10M7 11h10M7 15.5h6' },
  { id: 'search', label: '查找', icon: 'M10 6.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm4 7.5 3.5 3.5' },
  { id: 'batch', label: '批量', icon: 'M7 7h10v3H7zM7 14h10v3H7z' }
]

const railStyle = computed(() =>
  props.mode === 'rail' ? { width: '64px', flex: '0 0 64px' } : undefined
)

const toolButtons = ref<Partial<Record<WorkspaceTool, HTMLButtonElement | null>>>({})
const exportButton = ref<HTMLButtonElement | null>(null)

const visibleTools = computed(() =>
  props.mode === 'bottom'
    ? toolItems
    : toolItems.filter((tool) => tool.id !== 'document')
)

function setToolButton(id: WorkspaceTool) {
  return (element: Element | ComponentPublicInstance | null) => {
    toolButtons.value[id] = element instanceof HTMLButtonElement ? element : null
  }
}

function focusTool(tool: WorkspaceTool): void {
  toolButtons.value[tool]?.focus()
}

function focusExportButton(): void {
  exportButton.value?.focus()
}

function moveFocus(currentTool: WorkspaceTool | 'export', delta: number): void {
  const order = [...visibleTools.value.map((tool) => tool.id), 'export'] as Array<
    WorkspaceTool | 'export'
  >
  const index = order.indexOf(currentTool)
  if (index === -1) {
    return
  }

  const nextTool = order[(index + delta + order.length) % order.length]
  if (nextTool === 'export') {
    focusExportButton()
    return
  }

  focusTool(nextTool)
}

function onToolKeydown(event: KeyboardEvent, tool: WorkspaceTool): void {
  if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft' && event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
    return
  }

  event.preventDefault()
  const delta = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1
  moveFocus(tool, delta)
}

function onExportKeydown(event: KeyboardEvent): void {
  if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft' && event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
    return
  }

  event.preventDefault()
  const delta = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1
  moveFocus('export', delta)
}

function onActivate(tool: WorkspaceTool): void {
  emit('activate', tool)
}

function onExportClick(): void {
  emit('toggleExport')
}

defineExpose({ focusExportButton })
</script>

<template>
  <nav
    class="tool-rail"
    :class="`tool-rail--${mode}`"
    :style="railStyle"
    :aria-label="mode === 'rail' ? '审阅工具' : '工作台视图'"
    :data-side-panel-open="sidePanelOpen"
  >
    <div class="tool-rail__main">
      <button
        v-for="tool in visibleTools"
        :key="tool.id"
        :ref="setToolButton(tool.id)"
        type="button"
        class="tool-rail__button"
        :class="{
          'tool-rail__button--active': activeTool === tool.id
        }"
        :data-tool="tool.id"
        :title="tool.label"
        :aria-pressed="tool.id === 'document' ? undefined : activeTool === tool.id"
        :aria-current="tool.id === 'document' && activeTool === 'document' ? 'page' : undefined"
        @click="onActivate(tool.id)"
        @keydown="onToolKeydown($event, tool.id)"
      >
        <span
          v-if="activeTool === tool.id"
          class="tool-rail__active-indicator"
          aria-hidden="true"
        >
          ✓
        </span>
        <svg
          class="tool-rail__icon"
          viewBox="0 0 24 24"
          aria-hidden="true"
          focusable="false"
        >
          <path :d="tool.icon" />
        </svg>
        <span class="tool-rail__label">{{ tool.label }}</span>
      </button>
    </div>

    <div class="tool-rail__footer">
      <button
        ref="exportButton"
        type="button"
        class="tool-rail__button tool-rail__button--export"
        :class="{ 'tool-rail__button--active': exportOpen }"
        data-tool="export"
        title="导出"
        :aria-expanded="exportOpen"
        @click="onExportClick"
        @keydown="onExportKeydown"
      >
        <span v-if="exportOpen" class="tool-rail__active-indicator" aria-hidden="true">✓</span>
        <svg
          class="tool-rail__icon"
          viewBox="0 0 24 24"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M12 5v9m0 0 3-3m-3 3-3-3M6 17.5h12" />
        </svg>
        <span class="tool-rail__label">导出</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.tool-rail {
  display: flex;
  min-width: 0;
  gap: 10px;
  color: #344054;
  box-sizing: border-box;
}

.tool-rail--rail {
  flex-direction: column;
  height: 100%;
  padding: 10px 8px;
  gap: 8px;
}

.tool-rail--bottom {
  flex-direction: row;
  align-items: stretch;
  padding: 10px;
}

.tool-rail__main {
  display: flex;
  gap: 8px;
}

.tool-rail--rail .tool-rail__main {
  flex: 1;
  flex-direction: column;
  width: 100%;
}

.tool-rail--bottom .tool-rail__main {
  flex: 1;
  align-items: stretch;
}

.tool-rail__footer {
  display: flex;
}

.tool-rail--rail .tool-rail__footer {
  margin-top: auto;
  width: 100%;
}

.tool-rail--bottom .tool-rail__footer {
  margin-left: auto;
}

.tool-rail__button {
  position: relative;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 44px;
  min-height: 44px;
  width: 100%;
  padding: 8px 0;
  color: inherit;
  background: #f8f9fc;
  border: 1px solid #d8deea;
  border-radius: 12px;
  box-sizing: border-box;
  cursor: pointer;
}

.tool-rail--bottom .tool-rail__button {
  min-width: 72px;
  width: auto;
  padding: 10px 12px;
}

.tool-rail__button:hover,
.tool-rail__button:focus-visible {
  border-color: #96a4ee;
  outline: 3px solid rgba(126, 144, 255, 0.28);
  outline-offset: 2px;
}

.tool-rail__button--active {
  color: #243b98;
  background: #eef0ff;
  border-color: #7a8bea;
}

.tool-rail__active-indicator {
  position: absolute;
  top: 6px;
  right: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border: 1px solid currentColor;
  border-radius: 999px;
  background: #fff;
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
}

.tool-rail__icon {
  width: 20px;
  height: 20px;
  stroke: currentColor;
  stroke-width: 1.7;
  fill: none;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.tool-rail__label {
  font-size: 0.72rem;
  font-weight: 700;
  line-height: 1;
}
</style>
