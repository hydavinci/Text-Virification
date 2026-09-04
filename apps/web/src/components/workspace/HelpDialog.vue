<script setup lang="ts">
import AccessibleDialog from './AccessibleDialog.vue'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  close: []
}>()
</script>

<template>
  <AccessibleDialog
    :open="open"
    labelled-by="help-title"
    close-label="关闭使用帮助"
    close-data-attribute="data-close-help"
    @close="emit('close')"
  >
    <h2 id="help-title">使用帮助</h2>
    <p>
      选择文档场景和检查开关，可选配置术语表及禁用词，然后上传文件或粘贴文本。
    </p>
    <p>
      检查完成后可逐条接受、忽略或撤销建议，并通过查找替换和原文编辑完成最终校订。
    </p>
  </AccessibleDialog>
</template>
