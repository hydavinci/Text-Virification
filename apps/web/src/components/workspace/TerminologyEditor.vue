<script setup lang="ts">
import { ref, watch } from 'vue'

import {
  TerminologyImportError,
  bannedWordsExampleTxt,
  glossaryExampleCsv,
  readTerminologyFile,
  useTerminology
} from '../../composables/useTerminology'
import type { AnalyzeOptions } from '../../types/verification'

const props = defineProps<{
  kind: 'glossary' | 'banned'
  options: AnalyzeOptions
}>()

const emit = defineEmits<{
  'update:options': [options: AnalyzeOptions]
  notify: [message: string]
}>()

const terminology = useTerminology({
  glossary: props.options.glossary,
  bannedWords: props.options.bannedWords
})
const termOriginal = ref('')
const termStandard = ref('')
const bannedInput = ref('')
const errorMessage = ref<string | null>(null)

watch(
  () => props.options,
  (options) => {
    terminology.setGlossary(options.glossary)
    terminology.setBannedWords(options.bannedWords)
  },
  { deep: true }
)

function emitOptions(): void {
  emit('update:options', {
    ...props.options,
    glossary: terminology.glossary.value.map((term) => ({ ...term })),
    bannedWords: [...terminology.bannedWords.value]
  })
}

function termKey(original: string, standard: string): string {
  return JSON.stringify([original, standard])
}

function reportError(error: unknown): void {
  errorMessage.value =
    error instanceof TerminologyImportError
      ? error.message
      : '术语数据处理失败。'
}

function addGlossary(): void {
  try {
    const added = terminology.addGlossaryTerm(
      termOriginal.value,
      termStandard.value
    )
    if (!added) {
      errorMessage.value = '该术语对已存在。'
      return
    }
    termOriginal.value = ''
    termStandard.value = ''
    errorMessage.value = null
    emitOptions()
  } catch (error) {
    reportError(error)
  }
}

function addBannedWord(): void {
  try {
    const added = terminology.addBannedWord(bannedInput.value)
    if (!added) {
      errorMessage.value = '该禁用词已存在。'
      return
    }
    bannedInput.value = ''
    errorMessage.value = null
    emitOptions()
  } catch (error) {
    reportError(error)
  }
}

function removeGlossary(index: number): void {
  terminology.removeGlossaryTerm(index)
  errorMessage.value = null
  emitOptions()
}

function removeBanned(index: number): void {
  terminology.removeBannedWord(index)
  errorMessage.value = null
  emitOptions()
}

function clearCurrent(): void {
  if (props.kind === 'glossary') {
    terminology.clearGlossary()
  } else {
    terminology.clearBannedWords()
  }
  errorMessage.value = null
  emitOptions()
}

async function importFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }
  try {
    const content = await readTerminologyFile(file)
    const added =
      props.kind === 'glossary'
        ? terminology.importGlossary(content)
        : terminology.importBannedWords(content)
    errorMessage.value = null
    emitOptions()
    emit('notify', `成功导入 ${added} 项`)
  } catch (error) {
    reportError(error)
  } finally {
    input.value = ''
  }
}

function downloadExample(): void {
  const glossary = props.kind === 'glossary'
  const content = glossary ? glossaryExampleCsv() : bannedWordsExampleTxt()
  const filename = glossary ? '术语表示例.csv' : '禁用词示例.txt'
  const url = URL.createObjectURL(
    new Blob([content], { type: 'text/plain;charset=utf-8' })
  )
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <section class="settings-body">
    <template v-if="kind === 'glossary'">
      <h2>自定义术语表</h2>
      <p class="muted">规定原文写法应统一替换为的标准写法。</p>
      <div class="term-form">
        <label class="sr-only" for="term-original">原文写法</label>
        <input
          id="term-original"
          v-model="termOriginal"
          maxlength="200"
          placeholder="原文写法"
          @keyup.enter="addGlossary"
        />
        <span aria-hidden="true">→</span>
        <label class="sr-only" for="term-standard">规范写法</label>
        <input
          id="term-standard"
          v-model="termStandard"
          maxlength="200"
          placeholder="规范写法"
          @keyup.enter="addGlossary"
        />
        <button
          class="btn primary small"
          data-action="add-glossary"
          type="button"
          @click="addGlossary"
        >
          添加
        </button>
      </div>
    </template>

    <template v-else>
      <h2>禁用词库</h2>
      <p class="muted">命中后作为独立问题提示替换或删除。</p>
      <div class="term-form">
        <label class="sr-only" for="banned-word">输入禁用词</label>
        <input
          id="banned-word"
          v-model="bannedInput"
          maxlength="200"
          placeholder="输入禁用词"
          @keyup.enter="addBannedWord"
        />
        <button
          class="btn primary small"
          data-action="add-banned"
          type="button"
          @click="addBannedWord"
        >
          添加
        </button>
      </div>
    </template>

    <label class="import-btn">
      {{ kind === 'glossary' ? '导入 CSV / TSV / TXT' : '批量导入 CSV / TSV / TXT' }}
      <input
        type="file"
        accept=".csv,.tsv,.txt"
        :aria-label="kind === 'glossary' ? '导入术语表' : '导入禁用词'"
        @change="importFile"
      />
    </label>
    <button
      class="link-btn"
      data-action="download-example"
      type="button"
      @click="downloadExample"
    >
      下载示例
    </button>
    <button
      v-if="kind === 'glossary' ? terminology.glossary.value.length : terminology.bannedWords.value.length"
      class="link-btn danger"
      data-action="clear"
      type="button"
      @click="clearCurrent"
    >
      清空
    </button>

    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>

    <div v-if="kind === 'glossary'" class="chip-list">
      <div
        v-for="(term, index) in terminology.glossary.value"
        :key="termKey(term.original, term.standard)"
        class="term-chip"
      >
        <span class="original">{{ term.original }}</span>
        <span aria-hidden="true">→</span>
        <span class="standard">{{ term.standard }}</span>
        <button
          type="button"
          :aria-label="`删除术语 ${term.original}`"
          @click="removeGlossary(index)"
        >
          ×
        </button>
      </div>
      <p v-if="!terminology.glossary.value.length" class="empty">
        暂无自定义术语
      </p>
    </div>

    <div v-else class="banned-list">
      <span
        v-for="(word, index) in terminology.bannedWords.value"
        :key="word"
      >
        {{ word }}
        <button
          type="button"
          :aria-label="`删除禁用词 ${word}`"
          @click="removeBanned(index)"
        >
          ×
        </button>
      </span>
      <p v-if="!terminology.bannedWords.value.length" class="empty">
        暂无禁用词
      </p>
    </div>
  </section>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.settings-body {
  padding: 4px 20px 22px;
}
.settings-body h2 {
  margin: 18px 0 10px;
  font-size: 14px;
}
.muted,
.empty {
  color: var(--muted);
  font-size: 12px;
}
.term-form {
  display: flex;
  align-items: center;
  gap: 7px;
}
.term-form input {
  min-width: 0;
  flex: 1;
  padding: 9px 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  color: var(--text);
  background: var(--surface-2);
}
.term-form input:focus {
  border-color: var(--primary);
  outline: 3px solid rgba(37, 99, 235, .1);
}
.btn {
  padding: 9px 15px;
  border: 1px solid transparent;
  border-radius: 11px;
  font-weight: 700;
  cursor: pointer;
}
.btn.small {
  padding: 7px 11px;
  font-size: 12px;
}
.btn.primary {
  color: white;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  box-shadow: 0 7px 18px rgba(37, 99, 235, .2);
}
.import-btn {
  display: inline-block;
  margin: 12px 0;
  padding: 6px 10px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--primary);
  font-size: 12px;
  cursor: pointer;
}
.import-btn input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}
.link-btn {
  margin-left: 8px;
  border: 0;
  color: var(--primary);
  background: none;
  cursor: pointer;
  font-size: 12px;
}
.link-btn.danger {
  color: #dc2626;
}
.chip-list,
.banned-list {
  max-height: 240px;
  overflow: auto;
}
.term-chip {
  margin-bottom: 6px;
  padding: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  border-radius: 9px;
  background: var(--surface-2);
  font-size: 12px;
}
.term-chip .original {
  color: #dc2626;
  font-weight: 700;
}
.term-chip .standard {
  color: #059669;
  font-weight: 700;
}
.term-chip button,
.banned-list button {
  margin-left: auto;
  border: 0;
  color: var(--muted);
  background: none;
  cursor: pointer;
}
.banned-list {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}
.banned-list > span {
  padding: 6px 9px;
  display: flex;
  gap: 6px;
  border-radius: 999px;
  color: #be123c;
  background: #fff1f2;
  font-size: 12px;
}
[role='alert'] {
  color: #be123c;
  font-weight: 700;
}
@media (max-width: 680px) {
  .term-form {
    align-items: stretch;
    flex-wrap: wrap;
  }
}
</style>
