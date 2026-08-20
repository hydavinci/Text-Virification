<script setup lang="ts">
import { ref, watch, type ComponentPublicInstance } from 'vue'

import type { InspectorTab } from './workspaceLayout'

const props = defineProps<{
  activeTab: InspectorTab
}>()

const emit = defineEmits<{
  'update:activeTab': [tab: InspectorTab]
}>()

const tabs: InspectorTab[] = ['details', 'search']
const tabButtons = ref<Record<InspectorTab, HTMLButtonElement | null>>({
  details: null,
  search: null
})

function setTabButton(tab: InspectorTab) {
  return (element: Element | ComponentPublicInstance | null) => {
    tabButtons.value[tab] = element instanceof HTMLButtonElement ? element : null
  }
}

function focusTab(tab: InspectorTab): void {
  tabButtons.value[tab]?.focus()
}

function activateTab(tab: InspectorTab): void {
  emit('update:activeTab', tab)
}

function onTabKeydown(event: KeyboardEvent, tab: InspectorTab): void {
  const currentIndex = tabs.indexOf(tab)
  if (currentIndex === -1) {
    return
  }

  let nextIndex = -1
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    nextIndex = (currentIndex + 1) % tabs.length
  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
  } else if (event.key === 'Home') {
    nextIndex = 0
  } else if (event.key === 'End') {
    nextIndex = tabs.length - 1
  } else {
    return
  }

  event.preventDefault()
  activateTab(tabs[nextIndex] ?? tab)
}

watch(
  () => props.activeTab,
  (tab) => {
    focusTab(tab)
  },
  { flush: 'post' }
)
</script>

<template>
  <section class="context-inspector" aria-label="上下文检查器">
    <header class="context-inspector__header">
      <h2 class="context-inspector__title">上下文检查器</h2>

      <div class="context-inspector__tabs" role="tablist" aria-label="检查器标签">
        <button
          v-for="tab in tabs"
          :key="tab"
          :ref="setTabButton(tab)"
          type="button"
          class="context-inspector__tab"
          :class="{ 'context-inspector__tab--active': activeTab === tab }"
          role="tab"
          :data-tab="tab"
          :id="`context-inspector-tab-${tab}`"
          :aria-controls="`context-inspector-panel-${tab}`"
          :aria-selected="activeTab === tab"
          :tabindex="activeTab === tab ? 0 : -1"
          @click="activateTab(tab)"
          @keydown="onTabKeydown($event, tab)"
        >
          <span
            v-if="activeTab === tab"
            class="context-inspector__tab-indicator"
            aria-hidden="true"
          >
            ✓
          </span>
          {{ tab === 'details' ? '详情' : '查找' }}
        </button>
      </div>
    </header>

    <div class="context-inspector__panel">
      <section
        v-show="activeTab === 'details'"
        :id="`context-inspector-panel-details`"
        class="context-inspector__panel-body"
        role="tabpanel"
        aria-label="详情"
        :aria-labelledby="`context-inspector-tab-details`"
      >
        <slot name="details" />
      </section>

      <section
        v-show="activeTab === 'search'"
        :id="`context-inspector-panel-search`"
        class="context-inspector__panel-body"
        role="tabpanel"
        aria-label="查找"
        :aria-labelledby="`context-inspector-tab-search`"
      >
        <slot name="search" />
      </section>
    </div>
  </section>
</template>

<style scoped>
.context-inspector {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  background: #fff;
  border: 1px solid #dfe4f4;
  border-radius: 14px;
}

.context-inspector__header {
  display: grid;
  gap: 12px;
  padding: 14px 16px 12px;
  border-bottom: 1px solid #edf0f5;
}

.context-inspector__title {
  margin: 0;
  color: #243154;
  font-size: 0.92rem;
  line-height: 1.4;
}

.context-inspector__tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.context-inspector__tab {
  position: relative;
  min-height: 44px;
  padding: 9px 12px;
  color: #4256c9;
  font-weight: 700;
  background: #eef0ff;
  border: 1px solid #d4dcff;
  border-radius: 10px;
  cursor: pointer;
}

.context-inspector__tab--active {
  color: #fff;
  background: linear-gradient(135deg, #5c75f7, #7958d9);
  border-color: transparent;
}

.context-inspector__tab-indicator {
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
  color: #243154;
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
}

.context-inspector__tab:focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

.context-inspector__panel {
  min-height: 0;
  overflow: auto;
}

.context-inspector__panel-body {
  min-height: 0;
  padding: 16px;
}
</style>
