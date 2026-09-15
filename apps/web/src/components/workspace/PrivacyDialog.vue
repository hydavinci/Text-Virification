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
    <p>
      可选的语义发现默认关闭。明确启用且服务端允许后，会额外发送抽样的局部片段
      （包括未命中规则的文字）及相关自定义术语至所配置的模型服务，可能产生费用并增加等待时间。
      这不是全文检查，建议不会自动应用；敏感文档请勿启用。
    </p>
    <a data-privacy-details href="#privacy-retention">了解数据保留说明</a>
  </AccessibleDialog>
</template>
