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
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: var(--review-panel-radius);
}

.context-inspector__header {
  display: grid;
  gap: var(--review-space-3);
  padding: calc(var(--review-space-3) + 2px) var(--review-space-4) var(--review-space-3);
  border-bottom: 1px solid var(--review-border);
}

.context-inspector__title {
  margin: 0;
  color: var(--review-text);
  font-size: 0.92rem;
  line-height: 1.4;
}

.context-inspector__tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--review-space-2);
}

.context-inspector__tab {
  position: relative;
  min-width: 44px;
  min-height: 44px;
  padding: 9px var(--review-space-3);
  color: var(--review-accent);
  font-weight: 700;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 2px);
  cursor: pointer;
}

.context-inspector__tab--active {
  color: var(--review-surface);
  background: var(--review-accent);
  border-color: var(--review-accent);
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
  background: var(--review-surface);
  color: var(--review-text);
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
  padding: var(--review-space-4);
}
</style>
