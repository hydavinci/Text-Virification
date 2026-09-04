<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  labelledBy: string
  closeLabel: string
  closeDataAttribute: string
}>()

const emit = defineEmits<{
  close: []
}>()

const dialog = ref<HTMLElement | null>(null)
const closeAttributes = computed(() => ({
  [props.closeDataAttribute]: ''
}))
let opener: HTMLElement | null = null

watch(
  () => props.open,
  async (open) => {
    if (open) {
      opener =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null
      await nextTick()
      focusableElements()[0]?.focus()
      return
    }
    await nextTick()
    opener?.focus()
    opener = null
  }
)

function close(): void {
  emit('close')
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab') {
    return
  }
  const focusable = focusableElements()
  if (focusable.length === 0) {
    event.preventDefault()
    return
  }
  const first = focusable[0]
  const last = focusable.at(-1)
  if (
    (!event.shiftKey && document.activeElement === last) ||
    (event.shiftKey && document.activeElement === first)
  ) {
    event.preventDefault()
    ;(event.shiftKey ? last : first)?.focus()
  }
}

function focusableElements(): HTMLElement[] {
  if (dialog.value === null) {
    return []
  }
  return [...dialog.value.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )].filter((element) => !element.hasAttribute('hidden'))
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @click.self="close">
    <section
      ref="dialog"
      class="modal"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="labelledBy"
      @keydown="handleKeydown"
    >
      <button
        class="modal-close"
        type="button"
        v-bind="closeAttributes"
        :aria-label="closeLabel"
        @click="close"
      >
        ×
      </button>
      <slot />
    </section>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(2, 6, 23, .55);
}
.modal {
  width: min(560px, 100%);
  max-height: calc(100vh - 40px);
  padding: 28px;
  position: relative;
  overflow: auto;
  border-radius: 18px;
  background: var(--surface);
  box-shadow: var(--shadow);
}
.modal :deep(h2) {
  margin-top: 0;
}
.modal :deep(p) {
  color: var(--muted);
  line-height: 1.8;
}
.modal-close {
  position: absolute;
  right: 14px;
  top: 14px;
  border: 0;
  background: none;
  font-size: 24px;
  cursor: pointer;
}
</style>
