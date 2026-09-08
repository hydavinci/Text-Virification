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
      上传文件或粘贴文本，选择文档场景，点击“开始检查”。选中文件不会自动提交。
      在“检查设置”中调整合规开关、术语表及禁用词。
      PNG/JPEG 图片也可上传；图片和扫描 PDF 可选择中英文、英文或日文 OCR，
      日文识别不包含日文纠错。图片导出为可编辑 Word，不覆盖原图。
      扩展检查可按需开启中英文间距、空行和长句建议，长句只提示人工调整。
    </p>
    <p>检查覆盖字符、词汇、句子、标点格式、语篇语体和合规安全六个维度。结果供人工审阅，不替代专业判断。</p>
    <p>
      检查完成后可逐条接受、忽略或撤销建议，并通过查找替换和原文编辑完成最终校订。
      查找替换直接显示在右栏顶部，可按 Ctrl/Cmd+F 聚焦；手机端会先切换到右栏。
      在查找框中按 Enter 定位下一项，Shift+Enter 定位上一项。
      “撤销修改”按操作顺序回退替换和已保存的原文编辑，全部替换算一步；刷新页面后仍可继续撤销。
      重新检查或更换文档会开始新的修改记录。旧会话缺少审阅快照时，回退正文后仍需重新检查。
      正文统一使用段落视图；关闭“显示问题标记”可阅读干净正文，不改变已接受的修改或导出内容。
    </p>
  </AccessibleDialog>
</template>
