<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const dialog = ref<HTMLElement | null>(null)
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
      aria-labelledby="privacy-title"
      @keydown="handleKeydown"
    >
      <button
        class="modal-close"
        type="button"
        data-close-privacy
        aria-label="关闭隐私说明"
        @click="close"
      >
        ×
      </button>
      <h2 id="privacy-title">隐私说明</h2>
      <p>
        上传文件仅用于执行文档检查和导出。服务端按任务隔离存储，并在保留期结束后自动清理。
      </p>
      <p>
        启用云端语义复核时，仅发送规则命中位置附近的局部文本；未配置模型密钥时不会调用外部服务。
      </p>
      <a data-privacy-details href="#privacy-retention">了解数据保留说明</a>
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
.modal h2 {
  margin-top: 0;
}
.modal p {
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
