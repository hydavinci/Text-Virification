<script setup lang="ts">
import AccessibleDialog from './AccessibleDialog.vue'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

function close(): void {
  emit('close')
}
</script>

<template>
  <AccessibleDialog
    :open="props.open"
    labelled-by="privacy-title"
    close-label="关闭隐私说明"
    close-data-attribute="data-close-privacy"
    @close="close"
  >
    <h2 id="privacy-title">隐私说明</h2>
    <p>
      上传文件仅用于执行文档检查和导出。服务端按任务隔离存储，并在保留期结束后自动清理。
    </p>
    <p>
      启用云端语义复核时，仅发送规则命中位置附近的局部文本；未配置模型密钥时不会调用外部服务。
    </p>
    <a data-privacy-details href="#privacy-retention">了解数据保留说明</a>
  </AccessibleDialog>
</template>
