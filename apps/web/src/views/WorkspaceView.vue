<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { jobsApiKey } from '../api/jobs'
import { verificationApiKey } from '../api/verification'
import JobProgress from '../components/JobProgress.vue'
import DocumentViewer from '../components/workspace/DocumentViewer.vue'
import EditPreview from '../components/workspace/EditPreview.vue'
import ExportPanel from '../components/workspace/ExportPanel.vue'
import IssueList from '../components/workspace/IssueList.vue'
import PrivacyDialog from '../components/workspace/PrivacyDialog.vue'
import ReviewActions from '../components/workspace/ReviewActions.vue'
import SearchReplacePanel from '../components/workspace/SearchReplacePanel.vue'
import SourceInputPanel from '../components/workspace/SourceInputPanel.vue'
import TerminologyEditor from '../components/workspace/TerminologyEditor.vue'
import VerificationSettings from '../components/workspace/VerificationSettings.vue'
import WorkspaceHeader from '../components/workspace/WorkspaceHeader.vue'
import { useIssueNavigation } from '../composables/useIssueNavigation'
import { useVerificationExecution } from '../composables/useVerificationExecution'
import {
  bindWorkspaceExportAuthority,
  isWorkspaceExportAuthorityBoundToResult,
  type WorkspaceExportAuthority,
  type WorkspaceExportAuthoritySource,
  useWorkspaceSession
} from '../composables/useWorkspaceSession'
import {
  applyStoredWorkspaceTheme,
  persistWorkspaceTheme
} from '../composables/useWorkspaceTheme'
import { useVerificationWorkspace } from '../composables/useVerificationWorkspace'
import type {
  AnalyzeOptions,
  DocumentRevision,
  DraftDocumentRevision,
  IssueState,
  VerificationIssue,
  VerificationResult
} from '../types/verification'

const layers = [
  { id: 'character', name: '字符层', icon: 'A文', color: '#ef4444' },
  { id: 'vocabulary', name: '词汇层', icon: '词', color: '#f97316' },
  { id: 'sentence', name: '句子层', icon: '句', color: '#8b5cf6' },
  { id: 'format', name: '标点/格式层', icon: '符', color: '#0ea5e9' },
  { id: 'discourse', name: '语篇/语体层', icon: '篇', color: '#10b981' },
  { id: 'security', name: '合规/安全层', icon: '盾', color: '#d97706' }
]

const typeLabels: Record<string, string> = {
  typo: '错别字',
  variant_char: '异形词',
  width_mixed: '全半角混用',
  missing_char: '漏字/缺字',
  idiom_misuse: '成语误用',
  custom_term: '自定义术语',
  term_consistency: '术语不一致',
  expression: '语病/表达',
  grammar: '语法',
  logic: '逻辑',
  punctuation: '标点符号',
  spacing: '多余空格',
  number_format: '数字/格式',
  repetition: '重复词语',
  style: '文风/格式',
  colloquial: '口语化',
  banned_word: '禁用词',
  pii_id: '身份证号',
  pii_phone: '手机号',
  pii_email: '邮箱地址',
  pii_bank: '银行卡号',
  pii_key: '密钥/凭证',
  sensitive_politics: '涉政敏感词',
  sensitive_ethnic_religion: '民族宗教敏感词',
  sensitive_territory: '领土规范表述',
  ad_extreme: '广告法极限词'
}

const injectedJobsApi = inject(jobsApiKey)
if (!injectedJobsApi) {
  throw new Error('JobsApi is not provided.')
}
const jobsApi = injectedJobsApi
const verificationApi = inject(verificationApiKey, null)

const theme = ref<'light' | 'dark'>('light')
const selectedScenario = ref<AnalyzeOptions['scenario']>('general')
const enableSecurity = ref(true)
const enableSensitive = ref(true)
const enableAdExtreme = ref(false)
const trackChanges = ref(true)
const settingsTab = ref<'settings' | 'terms' | 'banned'>('settings')
const resultTab = ref<'issues' | 'summary'>('issues')
const textInput = ref('')
const fileSource = ref<File | null>(null)
const verificationWorkspace = useVerificationWorkspace()
const workspaceSession = useWorkspaceSession(
  window.sessionStorage,
  verificationWorkspace
)
const execution = useVerificationExecution({
  jobsApi,
  verificationApi,
  fileExecutionMode: 'jobs'
})
const result = computed(() => verificationWorkspace.result.value)
const issueStates = verificationWorkspace.issueStates
const selectedSuggestions = verificationWorkspace.selectedSuggestions
const canUndoLastBatch = computed(
  () => verificationWorkspace.canUndoLastBatch.value
)
const currentIssueStates = computed(() => issueStates.value)
const currentSelectedSuggestions = computed(
  () => selectedSuggestions.value
)
const issueNavigation = useIssueNavigation({
  issues: () => verificationWorkspace.visibleIssues.value
})
const selectedLayer = issueNavigation.selectedLayer
const selectedSeverity = issueNavigation.selectedSeverity
const selectedIssueId = issueNavigation.selectedIssueId
const visibleIssues = issueNavigation.visibleIssues
const glossary = ref<AnalyzeOptions['glossary']>([])
const bannedWords = ref<string[]>([])
const isAnalyzing = execution.isActive
const analysisStep = ref(0)
const errorMessage = computed(() => execution.error.value?.message ?? null)
const toast = ref<string | null>(null)
const showHelp = ref(false)
const showPrivacy = ref(false)
const segmentedView = ref(true)
const showFindReplace = ref(false)
const isExporting = ref(false)
const exportError = ref<string | null>(null)
const fileExportAuthority = ref<WorkspaceExportAuthority | null>(null)
const jobState = computed(() => {
  const job = execution.job.value
  const status = execution.jobStatus.value
  const stage = execution.stage.value
  if (!job || !status || !stage) {
    return null
  }
  const isFailure =
    status === 'failed' || status === 'partial' || status === 'expired'
  return {
    sourceName: job.source_name,
    status,
    stage,
    progress: execution.progress.value,
    message: execution.message.value,
    failureMessage: isFailure ? execution.message.value : null,
    connectionMessage: execution.connectionMessage.value
  }
})

let analysisTimer: ReturnType<typeof setInterval> | null = null
let loadedExecutionResult: VerificationResult | null = null
let toastTimer: ReturnType<typeof setTimeout> | null = null
let exportGeneration = 0
let disposed = false

const currentOptions = computed<AnalyzeOptions>(() => ({
  scenario: selectedScenario.value,
  enableSecurity: enableSecurity.value,
  enableSensitive: enableSensitive.value,
  enableAdExtreme: enableAdExtreme.value,
  glossary: glossary.value,
  bannedWords: bannedWords.value
}))

const pendingCount = computed(() => verificationWorkspace.summary.value.pending)
const acceptedCount = computed(() => verificationWorkspace.summary.value.accepted)
const rejectedCount = computed(() => verificationWorkspace.summary.value.rejected)

const modifiedText = computed(() => verificationWorkspace.modifiedText.value)
const currentRevisionText = computed(
  () =>
    verificationWorkspace.currentRevision.value?.text ??
    verificationWorkspace.result.value?.text ??
    ''
)
const selectedIssueState = computed<IssueState | null>(() => {
  const issueId = selectedIssueId.value
  return issueId === null
    ? null
    : issueStates.value[issueId] ?? 'pending'
})
const reviewActionsDisabled = computed(
  () =>
    isExporting.value ||
    verificationWorkspace.requiresReverification.value ||
    verificationWorkspace.visibleIssues.value.length === 0
)
const workspaceMutationLocked = computed(() => isExporting.value)
const exportBlockedReason = computed(() => {
  if (verificationWorkspace.hasReplacementConflicts.value) {
    return '存在重叠的已接受修改，请先解决冲突'
  }
  if (verificationWorkspace.requiresReverification.value) {
    return '当前文本已修改，请重新检查后再导出'
  }
  return null
})
const pdfExportNote = computed(() => {
  if (result.value?.file_type !== 'pdf') {
    return null
  }
  return result.value.pdf_metadata === undefined ||
    result.value.ocr_requirement !== undefined
    ? '扫描或混合 PDF 将导出为重建 DOCX，以保留 OCR 文本与版面。'
    : '文本 PDF 将保留 PDF 格式；纯插入修改可能被导出器明确拒绝。'
})
const statusAnnouncement = computed(() => {
  if (execution.isActive.value) {
    return execution.message.value || '正在执行文档检查'
  }
  if (toast.value) {
    return toast.value
  }
  if (result.value) {
    return `检查结果已就绪，共 ${result.value.summary.total} 项问题`
  }
  return '工作区已就绪'
})

async function handleUpload(file: File) {
  if (execution.isActive.value) {
    return
  }
  fileExportAuthority.value = null
  fileSource.value = file
  if (verificationApi && !confirmOptionalSettings()) {
    return
  }
  await execution.analyzeFile(file, currentOptions.value)
}

async function runTextAnalysis(submittedText: string) {
  if (execution.isActive.value) {
    return
  }
  const text = submittedText.trim()
  if (!text) {
    notify('请先输入需要检查的文本')
    return
  }
  if (!verificationApi || !confirmOptionalSettings()) {
    return
  }
  fileExportAuthority.value = null
  textInput.value = text
  fileSource.value = null
  await execution.analyzeText(text, currentOptions.value)
}

function confirmOptionalSettings() {
  if (glossary.value.length || bannedWords.value.length) {
    return true
  }
  return window.confirm('尚未设置自定义术语表和禁用词库，将仅执行通用规则检查。是否继续？')
}

function setIssueState(issueId: string, state: IssueState) {
  verificationWorkspace.setIssueState(issueId, state)
  saveSession()
}

function setVisibleIssueStates(issueIds: string[], state: IssueState) {
  verificationWorkspace.setIssueStates(issueIds, state)
  saveSession()
}

function undoIssue(issueId: string) {
  verificationWorkspace.undoIssue(issueId)
  saveSession()
}

function undoBatch() {
  verificationWorkspace.undoLastBatch()
  saveSession()
}

function selectSuggestion(issueId: string, suggestion: string | null) {
  verificationWorkspace.selectSuggestion(issueId, suggestion)
  saveSession()
}

function applyOptions(options: AnalyzeOptions) {
  selectedScenario.value = options.scenario
  enableSecurity.value = options.enableSecurity
  enableSensitive.value = options.enableSensitive
  enableAdExtreme.value = options.enableAdExtreme
  glossary.value = options.glossary.map((term) => ({ ...term }))
  bannedWords.value = [...options.bannedWords]
}

function invalidateSourceNavigation(): void {
  selectedIssueId.value = null
  selectedLayer.value = 'all'
  selectedSeverity.value = 'all'
}

function saveSearchReplacement(
  text: string,
  kind: 'current' | 'all',
  count: number
): void {
  const revision = verificationWorkspace.saveManualEdit(text)
  if (revision === null) {
    return
  }
  invalidateSourceNavigation()
  saveSession()
  notify(
    kind === 'all'
      ? `已替换 ${count} 处，请重新检查以刷新问题位置`
      : '已替换当前匹配，请重新检查以刷新问题位置'
  )
}

function saveFreeEdit(text: string): void {
  const revision = verificationWorkspace.saveManualEdit(text)
  if (revision === null) {
    return
  }
  invalidateSourceNavigation()
  saveSession()
}

function utf16IndexAtCodePointOffset(
  value: string,
  codePointOffset: number
): number | null {
  if (!Number.isInteger(codePointOffset) || codePointOffset < 0) {
    return null
  }
  let offset = 0
  let utf16Index = 0
  for (const character of value) {
    if (offset === codePointOffset) {
      return utf16Index
    }
    offset += 1
    utf16Index += character.length
  }
  return offset === codePointOffset ? utf16Index : null
}

async function recheck() {
  if (!verificationApi || !result.value || execution.isActive.value) {
    return
  }
  const source = result.value
  const exportAuthoritySource = captureFileExportAuthority()
  if (
    source.execution_mode === 'asynchronous' &&
    exportAuthoritySource === null
  ) {
    notify('当前文件缺少可验证的任务导出身份，无法重新检查')
    return
  }
  const priorAuthority = fileExportAuthority.value
  const submittedText = modifiedText.value
  let boundAuthority: WorkspaceExportAuthority | null = null
  textInput.value = submittedText
  fileSource.value = null
  await execution.analyzeText(
    textInput.value,
    currentOptions.value,
    (checked) => {
      const transformed = {
        ...checked,
        filename: source.filename,
        file_id: null,
        file_ext: null
      }
      if (exportAuthoritySource !== null) {
        boundAuthority = bindWorkspaceExportAuthority(
          exportAuthoritySource,
          transformed,
          submittedText
        )
        if (boundAuthority === null) {
          throw new Error('重新检查结果与提交文本或保留任务身份不匹配')
        }
      }
      return transformed
    }
  )
  fileExportAuthority.value = exportAuthoritySource === null
    ? null
    : execution.state.value === 'completed'
      ? boundAuthority
      : priorAuthority
  saveSession()
}

async function exportReport() {
  if (!verificationApi || !result.value) {
    return
  }
  exportError.value = null
  if (verificationWorkspace.requiresReverification.value) {
    notify('当前文本已修改，请重新检查后再导出报告')
    return
  }
  if (verificationWorkspace.hasReplacementConflicts.value) {
    notify('存在重叠的已接受修改，请先解决冲突后再导出')
    return
  }
  try {
    await verificationApi.exportReport(result.value)
    exportError.value = null
  } catch (error) {
    exportError.value =
      error instanceof Error ? error.message : '报告导出失败'
  }
}

async function exportModified() {
  if (!result.value) {
    return
  }
  exportError.value = null
  if (verificationWorkspace.hasReplacementConflicts.value) {
    notify('存在重叠的已接受修改，请先解决冲突后再导出')
    return
  }
  if (verificationWorkspace.requiresReverification.value) {
    notify('当前文本已修改，请重新检查后再导出')
    return
  }
  if (
    result.value.execution_mode === 'asynchronous'
  ) {
    const operation = beginExportOperation()
    if (!verificationApi || operation === null) {
      if (!verificationApi) {
        exportError.value = '异步文档导出服务不可用'
      }
      return
    }
    try {
      const revisionId = await persistDraftRevisionChain(operation)
      assertCurrentExportOperation(operation)
      await verificationApi.exportJob(
        operation.jobId,
        jobExportFormat(operation),
        revisionId,
        operation.trackChanges,
        () => isCurrentExportOperation(operation)
      )
      assertCurrentExportOperation(operation)
      notify('导出文件已生成')
    } catch (error) {
      if (
        !(error instanceof StaleExportOperationError) &&
        isCurrentExportOperation(operation)
      ) {
        exportError.value =
          error instanceof Error ? error.message : '修改文件导出失败'
      }
    } finally {
      if (isCurrentExportOperation(operation)) {
        isExporting.value = false
      }
    }
    return
  }
  if (fileExportAuthority.value !== null) {
    await exportRecheckedFile()
    return
  }
  if (!result.value.file_id || !verificationApi) {
    const text = trackChanges.value ? buildTrackedText() : modifiedText.value
    downloadText(text, `修改版_${result.value.filename.replace(/\.[^.]+$/, '')}.txt`)
    exportError.value = null
    return
  }

  function buildTrackedText() {
    if (!result.value) {
      return currentRevisionText.value
    }
    let text = result.value.text
    const accepted = verificationWorkspace.visibleIssues.value
      .filter(
        (issue) => issueStates.value[issue.issue_id] === 'accepted'
      )
      .filter((issue) => effectiveSuggestion(issue) !== null)
      .sort(
        (left, right) =>
          right.start - left.start ||
          right.end - left.end ||
          right.issue_id.localeCompare(left.issue_id)
      )
    for (const issue of accepted) {
      const start = utf16IndexAtCodePointOffset(text, issue.start)
      const end = utf16IndexAtCodePointOffset(text, issue.end)
      if (
        start === null ||
        end === null ||
        text.slice(start, end) !== issue.original
      ) {
        continue
      }
      const suggestion = effectiveSuggestion(issue)
      const tracked = `【删除：${issue.original}】【替换为：${
        suggestion || '（空）'
      }】`
      text = `${text.slice(0, start)}${tracked}${text.slice(end)}`
    }
    return text
  }
  const replacements = verificationWorkspace.visibleIssues.value
    .filter((issue) => issueStates.value[issue.issue_id] === 'accepted')
    .filter((issue) => effectiveSuggestion(issue) !== null)
    .map((issue) => ({
      original: issue.original,
      suggestion: effectiveSuggestion(issue) ?? '',
      position: issue.start,
      end_position: issue.end
    }))
  try {
    await verificationApi.exportOriginal(
      result.value,
      replacements,
      modifiedText.value,
      trackChanges.value
    )
    exportError.value = null
  } catch (error) {
    exportError.value =
      error instanceof Error ? error.message : '修改文件导出失败'
  }
}

function captureFileExportAuthority(): WorkspaceExportAuthoritySource | null {
  const currentResult = result.value
  if (
    fileExportAuthority.value !== null &&
    currentResult !== null &&
    isWorkspaceExportAuthorityBoundToResult(
      fileExportAuthority.value,
      currentResult
    )
  ) {
    return exportAuthoritySource(fileExportAuthority.value)
  }
  const jobId = execution.jobId.value
  if (
    currentResult === null ||
    currentResult.execution_mode !== 'asynchronous' ||
    jobId === null ||
    currentResult.document_id !== jobId
  ) {
    return null
  }
  const latestPersisted = [...verificationWorkspace.revisionChain.value]
    .reverse()
    .find((revision) => revision.persistence_state === 'persisted')
  return Object.freeze({
    jobId,
    documentId: currentResult.document_id,
    verificationRunId: currentResult.verification_run_id,
    sourceVersion: currentResult.source_version,
    fileType: currentResult.file_type,
    requiresOcrReconstruction:
      currentResult.file_type === 'pdf' &&
      (currentResult.pdf_metadata === undefined ||
        currentResult.pdf_metadata.pages.some(
          (page) => page.kind !== 'text'
        )),
    latestRevisionId: latestPersisted?.revision_id ?? null,
    latestRevisionNumber: latestPersisted?.revision_number ?? 0,
    persistedText: latestPersisted?.text ?? null
  })
}

function exportAuthoritySource(
  authority: WorkspaceExportAuthority
): WorkspaceExportAuthoritySource {
  return Object.freeze({
    jobId: authority.jobId,
    documentId: authority.documentId,
    verificationRunId: authority.verificationRunId,
    sourceVersion: authority.sourceVersion,
    fileType: authority.fileType,
    requiresOcrReconstruction: authority.requiresOcrReconstruction,
    latestRevisionId: authority.latestRevisionId,
    latestRevisionNumber: authority.latestRevisionNumber,
    persistedText: authority.persistedText
  })
}

interface RecheckedExportOperation {
  generation: number
  resultIdentity: string
  revisionIdentity: string
  authorityFingerprint: string
  authority: WorkspaceExportAuthority
  trackChanges: boolean
}

async function exportRecheckedFile(): Promise<void> {
  const operation = beginRecheckedExportOperation()
  if (operation === null || verificationApi === null) {
    if (verificationApi === null) {
      exportError.value = '异步文档导出服务不可用'
    }
    return
  }
  try {
    let revisionId = operation.authority.latestRevisionId
    if (
      revisionId === null ||
      operation.authority.persistedText !== currentRevisionText.value
    ) {
      const draft: DraftDocumentRevision = Object.freeze({
        revision_id: crypto.randomUUID(),
        document_id: operation.authority.documentId,
        verification_run_id: operation.authority.verificationRunId,
        source_version: operation.authority.sourceVersion,
        revision_number: null,
        created_at: new Date().toISOString(),
        parent_revision_id: operation.authority.latestRevisionId,
        persistence_state: 'draft',
        kind: 'manual',
        text: currentRevisionText.value
      })
      const persisted = await verificationApi.persistRevision(
        operation.authority.jobId,
        draft
      )
      assertCurrentRecheckedExportOperation(operation)
      const currentResult = result.value
      if (currentResult === null) {
        throw new StaleExportOperationError(
          'Export operation was superseded.'
        )
      }
      const nextAuthority = bindWorkspaceExportAuthority({
        ...operation.authority,
        latestRevisionId: persisted.revision_id,
        latestRevisionNumber: persisted.revision_number,
        persistedText: persisted.text
      }, currentResult, currentResult.text)
      if (nextAuthority === null) {
        throw new Error('保留的任务导出身份与重新检查结果不匹配')
      }
      fileExportAuthority.value = nextAuthority
      operation.authority = nextAuthority
      operation.authorityFingerprint = exportAuthorityFingerprint(nextAuthority)
      revisionId = persisted.revision_id
      saveSession()
    }
    assertCurrentRecheckedExportOperation(operation)
    await verificationApi.exportJob(
      operation.authority.jobId,
      operation.authority.requiresOcrReconstruction
        ? 'docx_reconstruction'
        : 'original_format',
      revisionId,
      operation.trackChanges,
      () => isCurrentRecheckedExportOperation(operation)
    )
    assertCurrentRecheckedExportOperation(operation)
    exportError.value = null
    notify('导出文件已生成')
  } catch (error) {
    if (
      !(error instanceof StaleExportOperationError) &&
      isCurrentRecheckedExportOperation(operation)
    ) {
      exportError.value =
        error instanceof Error ? error.message : '修改文件导出失败'
    }
  } finally {
    if (isCurrentRecheckedExportOperation(operation)) {
      isExporting.value = false
    }
  }
}

function beginRecheckedExportOperation(): RecheckedExportOperation | null {
  const currentResult = result.value
  const currentRevision = verificationWorkspace.currentRevision.value
  const authority = fileExportAuthority.value
  if (
    isExporting.value ||
    currentResult === null ||
    currentRevision === null ||
    authority === null ||
    !isWorkspaceExportAuthorityBoundToResult(authority, currentResult)
  ) {
    exportError.value = '异步文档缺少可验证的任务身份，无法导出'
    return null
  }
  exportGeneration += 1
  isExporting.value = true
  exportError.value = null
  return {
    generation: exportGeneration,
    resultIdentity: resultIdentityFingerprint(currentResult),
    revisionIdentity: revisionIdentityFingerprint(currentRevision),
    authorityFingerprint: exportAuthorityFingerprint(authority),
    authority,
    trackChanges: trackChanges.value
  }
}

function isCurrentRecheckedExportOperation(
  operation: RecheckedExportOperation
): boolean {
  const currentResult = result.value
  const currentRevision = verificationWorkspace.currentRevision.value
  const authority = fileExportAuthority.value
  return (
    !disposed &&
    operation.generation === exportGeneration &&
    currentResult !== null &&
    currentRevision !== null &&
    authority !== null &&
    isWorkspaceExportAuthorityBoundToResult(authority, currentResult) &&
    resultIdentityFingerprint(currentResult) === operation.resultIdentity &&
    revisionIdentityFingerprint(currentRevision) === operation.revisionIdentity &&
    exportAuthorityFingerprint(authority) === operation.authorityFingerprint
  )
}

function assertCurrentRecheckedExportOperation(
  operation: RecheckedExportOperation
): void {
  if (!isCurrentRecheckedExportOperation(operation)) {
    throw new StaleExportOperationError('Export operation was superseded.')
  }
}

function resultIdentityFingerprint(value: VerificationResult): string {
  return JSON.stringify([
    value.document_id,
    value.verification_run_id,
    value.source_version,
    value.text
  ])
}

function revisionIdentityFingerprint(
  value: Readonly<DocumentRevision>
): string {
  return JSON.stringify([
    value.revision_id,
    value.parent_revision_id,
    value.kind,
    value.text
  ])
}

function exportAuthorityFingerprint(
  value: WorkspaceExportAuthority
): string {
  return JSON.stringify([
    value.jobId,
    value.documentId,
    value.verificationRunId,
    value.sourceVersion,
    value.fileType,
    value.requiresOcrReconstruction,
    value.latestRevisionId,
    value.latestRevisionNumber,
    value.persistedText,
    value.provenance.resultDocumentId,
    value.provenance.resultVerificationRunId,
    value.provenance.resultSourceVersion,
    value.provenance.resultTextFingerprint,
    value.provenance.binding
  ])
}

function jobExportFormat(
  operation: ExportOperation
): 'docx_reconstruction' | 'original_format' {
  if (operation.requiresOcrReconstruction) {
    return 'docx_reconstruction'
  }
  return 'original_format'
}

interface ExportOperation {
  generation: number
  jobId: string
  documentId: string
  verificationRunId: string
  sourceVersion: string
  fileType: VerificationResult['file_type']
  requiresOcrReconstruction: boolean
  currentRevisionId: string | null
  currentRevisionText: string
  revisionFingerprint: string
  trackChanges: boolean
  chain: readonly Readonly<DocumentRevision>[]
}

class StaleExportOperationError extends Error {}

function beginExportOperation(): ExportOperation | null {
  const currentResult = result.value
  const currentRevision = verificationWorkspace.currentRevision.value
  const jobId = execution.jobId.value
  if (
    isExporting.value ||
    currentResult === null ||
    currentRevision === null ||
    jobId === null ||
    currentResult.document_id !== jobId
  ) {
    exportError.value = '异步文档缺少可验证的任务身份，无法导出'
    return null
  }
  exportGeneration += 1
  isExporting.value = true
  exportError.value = null
  const chain = [...verificationWorkspace.revisionChain.value]
  return {
    generation: exportGeneration,
    jobId,
    documentId: currentResult.document_id,
    verificationRunId: currentResult.verification_run_id,
    sourceVersion: currentResult.source_version,
    fileType: currentResult.file_type,
    requiresOcrReconstruction:
      currentResult.file_type === 'pdf' &&
      (currentResult.pdf_metadata === undefined ||
        currentResult.pdf_metadata.pages.some(
          (page) => page.kind !== 'text'
        )),
    currentRevisionId: currentRevision.revision_id,
    currentRevisionText: currentRevision.text,
    revisionFingerprint: revisionChainFingerprint(chain),
    trackChanges: trackChanges.value,
    chain
  }
}

function revisionChainFingerprint(
  chain: readonly Readonly<{
    revision_id: string | null
    document_id: string
    verification_run_id: string
    source_version: string
    parent_revision_id: string | null
    kind: string
    text: string
  }>[]
): string {
  return JSON.stringify(
    chain.map((revision) => [
      revision.revision_id,
      revision.document_id,
      revision.verification_run_id,
      revision.source_version,
      revision.parent_revision_id,
      revision.kind,
      revision.text
    ])
  )
}

function isCurrentExportOperation(operation: ExportOperation): boolean {
  const currentResult = result.value
  const currentRevision = verificationWorkspace.currentRevision.value
  return (
    !disposed &&
    operation.generation === exportGeneration &&
    currentResult !== null &&
    currentRevision !== null &&
    execution.jobId.value === operation.jobId &&
    currentResult.document_id === operation.documentId &&
    currentResult.verification_run_id === operation.verificationRunId &&
    currentResult.source_version === operation.sourceVersion &&
    currentRevision.revision_id === operation.currentRevisionId &&
    currentRevision.text === operation.currentRevisionText &&
    revisionChainFingerprint(verificationWorkspace.revisionChain.value) ===
      operation.revisionFingerprint
  )
}

function assertCurrentExportOperation(operation: ExportOperation): void {
  if (!isCurrentExportOperation(operation)) {
    throw new StaleExportOperationError('Export operation was superseded.')
  }
}

function invalidateExportOperation(): void {
  exportGeneration += 1
  isExporting.value = false
}

async function persistDraftRevisionChain(
  operation: ExportOperation
): Promise<string | null> {
  if (!verificationApi) {
    throw new Error('修订持久化服务不可用')
  }
  for (const revision of operation.chain) {
    if (revision.persistence_state !== 'draft') {
      continue
    }
    const persisted = await verificationApi.persistRevision(
      operation.jobId,
      revision as DraftDocumentRevision
    )
    assertCurrentExportOperation(operation)
    if (!verificationWorkspace.hydratePersistedRevision(persisted)) {
      throw new Error('服务端修订与当前工作区不一致')
    }
    assertCurrentExportOperation(operation)
  }
  saveSession()
  const current = verificationWorkspace.currentRevision.value
  return current?.persistence_state === 'persisted'
    ? current.revision_id
    : null
}

function downloadText(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function resetWorkspace() {
  invalidateExportOperation()
  exportError.value = null
  fileExportAuthority.value = null
  execution.reset()
  verificationWorkspace.clearResult()
  loadedExecutionResult = null
  invalidateSourceNavigation()
  resultTab.value = 'issues'
  showFindReplace.value = false
  fileSource.value = null
  textInput.value = ''
  analysisStep.value = 0
  workspaceSession.clear()
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  applyTheme()
}

function applyTheme() {
  persistWorkspaceTheme(
    theme.value,
    window.localStorage,
    document.documentElement
  )
}

function notify(message: string) {
  toast.value = message
  if (toastTimer) {
    window.clearTimeout(toastTimer)
  }
  toastTimer = window.setTimeout(() => {
    toast.value = null
  }, 2600)
}

function saveSession() {
  if (!result.value) {
    return
  }
  workspaceSession.save({
    options: currentOptions.value,
    filters: {
      layer: selectedLayer.value,
      severity: selectedSeverity.value
    },
    viewMode: segmentedView.value ? 'sentence' : 'continuous',
    ui: {
      settingsTab: settingsTab.value,
      resultTab: resultTab.value,
      showFindReplace: showFindReplace.value,
      trackChanges: trackChanges.value,
      selectedIssueId: selectedIssueId.value
    },
    jobId: execution.jobId.value,
    exportAuthority: fileExportAuthority.value
  })
}

function restoreSession() {
  const restored = workspaceSession.restore()
  if (restored === null) {
    return
  }
  applyOptions(restored.options)
  selectedLayer.value = restored.filters.layer
  selectedSeverity.value = restored.filters.severity
  segmentedView.value = restored.viewMode === 'sentence'
  settingsTab.value = restored.ui.settingsTab
  resultTab.value = restored.ui.resultTab
  showFindReplace.value = restored.ui.showFindReplace
  trackChanges.value = restored.ui.trackChanges
  selectedIssueId.value = restored.ui.selectedIssueId
  fileExportAuthority.value = restored.exportAuthority
  if (
    restored.jobId !== null &&
    result.value !== null &&
    !execution.restoreJobContext(restored.jobId, result.value)
  ) {
    resetWorkspace()
    return
  }
  if (verificationWorkspace.requiresReverification.value) {
    invalidateSourceNavigation()
  }
}

function effectiveSuggestion(issue: VerificationIssue): string | null {
  return Object.prototype.hasOwnProperty.call(
    selectedSuggestions.value,
    issue.issue_id
  )
    ? selectedSuggestions.value[issue.issue_id]
    : issue.suggestion
}

function handleKeyboard(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f' && result.value) {
    event.preventDefault()
    showFindReplace.value = true
    return
  }
  if (event.key === 'Escape') {
    showFindReplace.value = false
    showHelp.value = false
    showPrivacy.value = false
  }
}

watch(
  [
    () => verificationWorkspace.currentRevision.value,
    () => issueStates.value,
    () => selectedSuggestions.value
  ],
  saveSession,
  { deep: true }
)

watch(
  [
    () => currentOptions.value,
    () => selectedLayer.value,
    () => selectedSeverity.value,
    () => segmentedView.value,
    () => settingsTab.value,
    () => resultTab.value,
    () => showFindReplace.value,
    () => trackChanges.value,
    () => selectedIssueId.value,
    () => fileExportAuthority.value
  ],
  saveSession,
  { deep: true }
)

watch(
  [() => execution.state.value, () => execution.result.value],
  ([executionState, executionResult]) => {
    if (executionState === 'submitting') {
      invalidateExportOperation()
      loadedExecutionResult = null
      return
    }
    if (
      executionState !== 'completed' ||
      executionResult === null ||
      executionResult === loadedExecutionResult
    ) {
      return
    }
    loadedExecutionResult = executionResult
    invalidateExportOperation()
    exportError.value = null
    verificationWorkspace.loadResult(executionResult)
    invalidateSourceNavigation()
    resultTab.value = 'issues'
    showFindReplace.value = false
    analysisStep.value = 6
    saveSession()
  }
)

watch(
  () => execution.isActive.value,
  (active) => {
    if (analysisTimer) {
      window.clearInterval(analysisTimer)
      analysisTimer = null
    }
    if (!active) {
      return
    }
    analysisStep.value = 0
    analysisTimer = window.setInterval(() => {
      analysisStep.value = Math.min(analysisStep.value + 1, 5)
    }, 420)
  }
)

onMounted(() => {
  theme.value = applyStoredWorkspaceTheme(
    window.localStorage,
    document.documentElement
  )
  applyTheme()
  restoreSession()
  document.addEventListener('keydown', handleKeyboard)
})

onBeforeUnmount(() => {
  disposed = true
  invalidateExportOperation()
  execution.dispose()
  document.removeEventListener('keydown', handleKeyboard)
  if (analysisTimer) {
    window.clearInterval(analysisTimer)
  }
  if (toastTimer) {
    window.clearTimeout(toastTimer)
  }
})
</script>

<template>
  <div class="shell">
    <WorkspaceHeader
      :theme="theme"
      :has-result="result !== null"
      @reset="resetWorkspace"
      @open-privacy="showPrivacy = true"
      @open-help="showHelp = true"
      @toggle-theme="toggleTheme"
    >
      <template #exports>
        <ExportPanel
          :track-changes="trackChanges"
          :report-disabled="exportBlockedReason !== null"
          :modified-disabled="exportBlockedReason !== null"
          :recheck-disabled="isAnalyzing"
          :busy="isExporting"
          :blocked-reason="exportBlockedReason"
          @update:track-changes="trackChanges = $event"
          @recheck="recheck"
          @export-report="exportReport"
          @export-modified="exportModified"
        />
        <small
          v-if="pdfExportNote"
          class="pdf-export-note"
        >
          {{ pdfExportNote }}
        </small>
      </template>
    </WorkspaceHeader>

    <p
      class="visually-hidden"
      data-workspace-status
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {{ statusAnnouncement }}
    </p>
    <p
      v-if="workspaceSession.warning.value"
      class="session-warning"
      data-session-warning
      role="alert"
      aria-live="assertive"
    >
      {{ workspaceSession.warning.value }}
    </p>
    <div
      v-if="exportError"
      class="export-error"
      data-export-error
      role="alert"
      aria-live="assertive"
    >
      <span>{{ exportError }}</span>
      <button
        type="button"
        data-dismiss-export-error
        aria-label="关闭导出错误"
        @click="exportError = null"
      >
        ×
      </button>
    </div>

    <main v-if="!result" class="landing">
      <section class="hero">
        <div>
          <span class="eyebrow">DOCUMENT QUALITY GATE</span>
          <h1>解决文件交付的最后一英里</h1>
          <p>从字符、词汇、句子、格式、语篇与合规六个维度逐句扫描，精准定位中英文内容问题。</p>
        </div>
        <div class="radar" aria-hidden="true"><span></span></div>
      </section>

      <div class="landing-grid">
        <section class="input-card">
          <SourceInputPanel
            v-model:text="textInput"
            :busy="isAnalyzing"
            :server-error="errorMessage"
            @submit-file="handleUpload"
            @submit-text="runTextAnalysis"
          />

          <div v-if="isAnalyzing" class="loading-card" role="status" aria-live="polite">
            <div class="spinner"></div>
            <div>
              <strong>正在执行六层检查</strong>
              <p>步骤 {{ Math.min(analysisStep + 1, 6) }}/6 · 请勿关闭页面</p>
            </div>
          </div>
          <JobProgress v-if="jobState" :state="jobState" />
          <p class="privacy-note">仅为完成检查处理文档；建议不要上传涉密文件。任务数据默认 24 小时后清理。</p>
        </section>

        <aside class="settings-card">
          <div class="side-tabs">
            <button :class="{ active: settingsTab === 'settings' }" @click="settingsTab = 'settings'">检查设置</button>
            <button :class="{ active: settingsTab === 'terms' }" @click="settingsTab = 'terms'">
              术语 {{ glossary.length }}
            </button>
            <button :class="{ active: settingsTab === 'banned' }" @click="settingsTab = 'banned'">
              禁用词 {{ bannedWords.length }}
            </button>
          </div>

          <VerificationSettings
            v-if="settingsTab === 'settings'"
            :options="currentOptions"
            @update:options="applyOptions"
          />
          <TerminologyEditor
            v-else
            :kind="settingsTab === 'terms' ? 'glossary' : 'banned'"
            :options="currentOptions"
            @update:options="applyOptions"
            @notify="notify"
          />
        </aside>
      </div>

      <section class="layers">
        <article v-for="layer in layers" :key="layer.id" :style="{ '--layer-color': layer.color }">
          <span>{{ layer.icon }}</span><strong>{{ layer.name }}</strong>
        </article>
      </section>
    </main>

    <main v-else class="review-workspace">
      <p
        v-if="errorMessage"
        class="execution-error"
        data-review-execution-error
        role="alert"
        aria-live="assertive"
      >
        {{ errorMessage }}
      </p>
      <p
        v-if="execution.jobStatus.value === 'partial'"
        class="execution-warning"
        data-execution-warning
        role="status"
        aria-live="polite"
      >
        {{ execution.message.value }}
      </p>
      <section class="stats-strip">
        <article><small>{{ result.stats.primary_label }}</small><strong>{{ result.stats.primary_count }}</strong></article>
        <article><small>发现问题</small><strong>{{ result.summary.total }}</strong></article>
        <article><small>已接受</small><strong class="success">{{ acceptedCount }}</strong></article>
        <article><small>已忽略</small><strong class="muted-text">{{ rejectedCount }}</strong></article>
        <article><small>待处理</small><strong class="warning">{{ pendingCount }}</strong></article>
        <article><small>文件</small><strong class="filename">{{ result.filename }}</strong></article>
      </section>

      <SearchReplacePanel
        v-if="showFindReplace"
        :text="currentRevisionText"
        :disabled="workspaceMutationLocked"
        @replace-text="saveSearchReplacement"
        @close="showFindReplace = false"
      />

      <section class="review-toolbar">
        <div>
          <button
            class="btn ghost small"
            type="button"
            data-action="toggle-search-replace"
            :aria-expanded="showFindReplace"
            :disabled="workspaceMutationLocked"
            @click="showFindReplace = !showFindReplace"
          >
            查找替换
          </button>
          <button
            class="btn ghost small"
            type="button"
            :class="{ active: segmentedView }"
            :aria-pressed="segmentedView"
            @click="segmentedView = !segmentedView"
          >
            {{ segmentedView ? '句段视图' : '连续视图' }}
          </button>
        </div>
        <ReviewActions
          :selected-issue-id="selectedIssueId"
          :selected-issue-state="selectedIssueState"
          :visible-issue-ids="visibleIssues.map((issue) => issue.issue_id)"
          :summary="verificationWorkspace.summary.value"
          :has-conflicts="verificationWorkspace.hasReplacementConflicts.value"
          :conflict-issue-ids="
            verificationWorkspace.replacementConflictIssueIds.value
          "
          :can-undo-last-batch="canUndoLastBatch"
          :disabled="reviewActionsDisabled"
          @set-issue-state="setIssueState"
          @undo-issue="undoIssue"
          @set-visible-state="setVisibleIssueStates"
          @undo-batch="undoBatch"
        />
      </section>

      <div class="review-grid">
        <section class="document-panel">
          <header>
            <div>
              <strong>
                {{
                  verificationWorkspace.requiresReverification.value
                    ? '当前手工修订'
                    : '源文本'
                }}
              </strong>
              <small>{{ result.filename }}</small>
            </div>
          </header>
          <EditPreview
            :text="currentRevisionText"
            :preview-text="modifiedText"
            :disabled="workspaceMutationLocked"
            @save="saveFreeEdit"
          >
            <pre
              v-if="verificationWorkspace.requiresReverification.value"
              class="current-revision-text"
              data-current-revision
            >{{ currentRevisionText }}</pre>
            <DocumentViewer
              v-else
              :result="result"
              :issues="visibleIssues"
              :issue-states="currentIssueStates"
              :selected-issue-id="selectedIssueId"
              :mode="segmentedView ? 'sentence' : 'continuous'"
              @select-issue="issueNavigation.selectIssue"
            />
          </EditPreview>
        </section>

        <aside class="issues-panel">
          <header class="issues-header">
            <div class="side-tabs compact-tabs">
              <button :class="{ active: resultTab === 'issues' }" @click="resultTab = 'issues'">问题列表</button>
              <button :class="{ active: resultTab === 'summary' }" @click="resultTab = 'summary'">检查摘要</button>
            </div>
            <span>{{ visibleIssues.length }} 项</span>
          </header>

          <div
            v-if="
              resultTab === 'issues' &&
              verificationWorkspace.requiresReverification.value
            "
            class="reverification-state"
            role="status"
          >
            文本已修改。请重新检查后再使用问题筛选、定位和审阅操作。
          </div>
          <template v-else-if="resultTab === 'issues'">
            <IssueList
              :issues="visibleIssues"
              :selected-issue-id="selectedIssueId"
              :issue-states="currentIssueStates"
              :selected-suggestions="currentSelectedSuggestions"
              :selected-layer="selectedLayer"
              :selected-severity="selectedSeverity"
              :layer-options="layers"
              :type-labels="typeLabels"
              :disabled="workspaceMutationLocked"
              @select-issue="issueNavigation.selectIssue"
              @update:selected-layer="selectedLayer = $event"
              @update:selected-severity="selectedSeverity = $event"
              @update:suggestion="selectSuggestion"
              @set-state="setIssueState"
            />
          </template>

          <div v-else class="summary-panel">
            <h3>按检查层级</h3>
            <div v-for="(count, label) in result.summary.by_layer" :key="label" class="summary-row">
              <span>{{ label }}</span><strong>{{ count }}</strong>
            </div>
            <h3>按问题类型</h3>
            <div v-for="(count, label) in result.summary.by_type" :key="label" class="summary-row">
              <span>{{ label }}</span><strong>{{ count }}</strong>
            </div>
          </div>
        </aside>
      </div>
    </main>

    <div v-if="toast" class="toast" role="status" aria-live="polite">{{ toast }}</div>
    <PrivacyDialog :open="showPrivacy" @close="showPrivacy = false" />
    <div v-if="showHelp" class="modal-backdrop" @click.self="showHelp = false">
      <section class="modal" role="dialog" aria-modal="true" aria-labelledby="help-title">
        <button class="modal-close" type="button" aria-label="关闭使用帮助" @click="showHelp = false">×</button>
        <h2 id="help-title">使用帮助</h2>
        <p>选择文档场景和检查开关，可选配置术语表及禁用词，然后上传文件或粘贴文本。</p>
        <p>检查完成后可逐条接受、忽略或撤销建议，并通过查找替换和原文编辑完成最终校订。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
:global(*) { box-sizing: border-box; }
:global(html) { color-scheme: light; }
:global(html[data-theme='dark']) { color-scheme: dark; }
:global(body) {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
}
.shell {
  --primary: #2563eb;
  --primary-2: #06b6d4;
  --bg: #f5f7fb;
  --surface: #ffffff;
  --surface-2: #f8fafc;
  --border: #e2e8f0;
  --text: #172033;
  --muted: #64748b;
  --shadow: 0 18px 55px rgba(15, 23, 42, .09);
  min-height: 100vh;
  background:
    radial-gradient(circle at 8% 0%, rgba(37, 99, 235, .1), transparent 28rem),
    radial-gradient(circle at 96% 8%, rgba(6, 182, 212, .09), transparent 25rem),
    var(--bg);
}
:global(html[data-theme='dark']) .shell {
  --bg: #0c1220;
  --surface: #131c2e;
  --surface-2: #0f172a;
  --border: #26344c;
  --text: #e5edf8;
  --muted: #9aa9bd;
  --shadow: 0 18px 55px rgba(0, 0, 0, .28);
}
button, input, textarea, select { font: inherit; }
button { color: inherit; }
.topbar {
  height: 68px;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  backdrop-filter: blur(18px);
}
.brand { display: flex; align-items: center; gap: 11px; border: 0; background: none; cursor: pointer; text-align: left; }
.brand-mark {
  width: 38px; height: 38px; display: grid; place-items: center; border-radius: 13px;
  color: white; font-weight: 900; background: linear-gradient(135deg, var(--primary), var(--primary-2));
  box-shadow: 0 8px 20px rgba(37, 99, 235, .28);
}
.brand strong, .brand small { display: block; }
.brand strong { font-size: 16px; }
.brand small { color: var(--muted); font-size: 11px; margin-top: 1px; }
.top-actions { display: flex; align-items: center; gap: 8px; }
.icon-btn { width: 36px; height: 36px; border-radius: 11px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; }
.btn { border: 1px solid transparent; border-radius: 11px; padding: 9px 15px; font-weight: 700; cursor: pointer; transition: .2s; }
.btn:disabled { opacity: .55; cursor: wait; }
.btn.primary { color: white; background: linear-gradient(135deg, var(--primary), var(--primary-2)); box-shadow: 0 7px 18px rgba(37, 99, 235, .2); }
.btn.ghost { border-color: var(--border); background: var(--surface); }
.btn.small { padding: 7px 11px; font-size: 12px; }
.btn.active { border-color: var(--primary); color: var(--primary); }
.btn.accept { background: #dcfce7; color: #15803d; }
.btn.reject { background: #fff1f2; color: #be123c; }
.landing { max-width: 1440px; margin: auto; padding: 36px 28px 50px; }
.hero {
  min-height: 215px; padding: 38px 44px; display: flex; align-items: center; justify-content: space-between;
  overflow: hidden; border-radius: 26px; color: white; background:
    linear-gradient(110deg, rgba(18, 67, 148, .98), rgba(22, 109, 162, .95) 55%, rgba(15, 145, 148, .92));
  box-shadow: var(--shadow);
}
.hero > div:first-child { max-width: 800px; }
.eyebrow { font-size: 11px; letter-spacing: .2em; opacity: .76; font-weight: 800; }
.hero h1 { font-size: clamp(30px, 4vw, 54px); line-height: 1.08; margin: 14px 0; letter-spacing: -.04em; }
.hero p { max-width: 700px; margin: 0; line-height: 1.8; opacity: .82; }
.radar { width: 160px; height: 160px; border: 1px solid rgba(255,255,255,.22); border-radius: 50%; position: relative; background: repeating-radial-gradient(circle, transparent 0 24px, rgba(255,255,255,.12) 25px 26px); }
.radar::before, .radar::after { content: ''; position: absolute; background: rgba(255,255,255,.16); }
.radar::before { width: 100%; height: 1px; top: 50%; }
.radar::after { width: 1px; height: 100%; left: 50%; }
.radar span { position: absolute; inset: 50% 50% 0 50%; transform-origin: top left; background: conic-gradient(from 0deg, rgba(255,255,255,.38), transparent 55deg); animation: sweep 4s linear infinite; }
@keyframes sweep { to { transform: rotate(360deg); } }
.landing-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(340px, .8fr); gap: 22px; margin-top: 22px; }
.input-card, .settings-card, .document-panel, .issues-panel {
  border: 1px solid var(--border); border-radius: 20px; background: color-mix(in srgb, var(--surface) 96%, transparent); box-shadow: var(--shadow); overflow: hidden;
}
.input-card { padding: 24px; }
.side-tabs { display: flex; gap: 5px; padding: 4px; border-radius: 12px; background: var(--surface-2); }
.side-tabs button { padding: 9px 17px; border: 0; border-radius: 9px; color: var(--muted); background: transparent; cursor: pointer; font-weight: 700; }
.side-tabs button.active { color: var(--primary); background: var(--surface); box-shadow: 0 3px 10px rgba(15,23,42,.08); }
.document-editor {
  width: 100%; resize: vertical; border: 1px solid var(--border); border-radius: 15px; color: var(--text); background: var(--surface-2); outline: none;
}
input:focus, select:focus { border-color: var(--primary); outline: 3px solid rgba(37, 99, 235, .1); }
.privacy-note { margin: 17px 0 0; color: var(--muted); font-size: 12px; }
.loading-card { margin-top: 16px; padding: 14px; display: flex; align-items: center; gap: 12px; border-radius: 13px; background: #eff6ff; color: #1d4ed8; }
.loading-card p { margin: 3px 0 0; font-size: 12px; }
.spinner { width: 27px; height: 27px; border: 3px solid #bfdbfe; border-top-color: #2563eb; border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.settings-card { min-height: 460px; }
.settings-card > .side-tabs { margin: 16px; }
.switch { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0; color: var(--muted); font-size: 13px; }
.switch input { width: 35px; height: 20px; accent-color: var(--primary); }
.switch.compact { padding: 0 8px; }
.find-panel input, .filters select {
  min-width: 0; padding: 9px 10px; border: 1px solid var(--border); border-radius: 9px; color: var(--text); background: var(--surface-2);
}
.layers { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-top: 18px; }
.layers article { padding: 13px; display: flex; gap: 9px; align-items: center; border: 1px solid var(--border); border-top: 3px solid var(--layer-color); border-radius: 13px; background: var(--surface); }
.layers article span { color: var(--layer-color); font-weight: 900; }
.layers article strong { font-size: 12px; }
.review-workspace { height: calc(100vh - 68px); padding: 14px 18px 18px; display: flex; flex-direction: column; gap: 11px; }
.stats-strip { display: grid; grid-template-columns: repeat(5, minmax(90px, 130px)) minmax(220px, 1fr); gap: 8px; }
.stats-strip article { padding: 10px 13px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.stats-strip small, .stats-strip strong { display: block; }
.stats-strip small { color: var(--muted); font-size: 10px; }
.stats-strip strong { margin-top: 2px; font-size: 18px; }
.stats-strip .filename { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.success { color: #059669; }.warning { color: #d97706; }.muted-text { color: var(--muted); }
.execution-warning,
.execution-error {
  margin: 0;
  padding: 10px 13px;
  border-radius: 12px;
  font-size: 12px;
}
.execution-warning { border: 1px solid #f59e0b; color: #92400e; background: #fffbeb; }
.execution-error { border: 1px solid #ef4444; color: #991b1b; background: #fef2f2; }
.session-warning {
  margin: 12px 18px 0;
  padding: 10px 13px;
  border: 1px solid #ef4444;
  border-radius: 12px;
  color: #991b1b;
  background: #fef2f2;
  font-size: 12px;
}
.export-error {
  margin: 12px 18px 0;
  padding: 10px 13px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #ef4444;
  border-radius: 12px;
  color: #991b1b;
  background: #fef2f2;
  font-size: 12px;
}
.export-error button {
  border: 0;
  color: inherit;
  background: transparent;
  cursor: pointer;
  font-size: 18px;
}
.visually-hidden {
  width: 1px;
  height: 1px;
  padding: 0;
  position: absolute;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
.review-toolbar, .find-panel { padding: 9px; display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.review-toolbar > div:first-child { display: flex; gap: 7px; }
.find-panel { justify-content: flex-start; }
.review-grid { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(370px, .75fr); gap: 12px; }
.document-panel, .issues-panel { min-height: 0; display: flex; flex-direction: column; }
.document-panel > header, .issues-header { min-height: 54px; padding: 10px 15px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }
.document-panel header small { display: block; margin-top: 2px; color: var(--muted); }
.document-content, .document-editor { flex: 1; min-height: 0; margin: 0; padding: 24px 28px; overflow: auto; white-space: pre-wrap; color: var(--text); background: var(--surface); font: 15px/2 ui-monospace, SFMono-Regular, Menlo, monospace; }
.document-content:not(.preview) { padding: 0; }
.document-content.preview { color: #075985; }
.document-editor { border: 0; border-radius: 0; resize: none; }
.current-revision-text {
  min-height: 100%;
  margin: 0;
  padding: 24px 28px;
  white-space: pre-wrap;
  color: var(--text);
  background: var(--surface);
  font: 15px/2 ui-monospace, SFMono-Regular, Menlo, monospace;
}
.reverification-state {
  margin: 14px;
  padding: 16px;
  border: 1px solid #f59e0b;
  border-radius: 12px;
  color: #92400e;
  background: #fffbeb;
  line-height: 1.7;
  font-size: 12px;
}
.compact-tabs { padding: 3px; }
.compact-tabs button { padding: 7px 10px; font-size: 12px; }
.issues-header > span { color: var(--muted); font-size: 12px; }
.summary-panel { padding: 16px; overflow: auto; }
.summary-panel h3 { margin: 8px 0 10px; font-size: 13px; }
.summary-row { padding: 8px 0; display: flex; justify-content: space-between; border-bottom: 1px solid var(--border); font-size: 12px; }
.toast { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%); z-index: 40; padding: 11px 18px; border-radius: 10px; color: white; background: #172033; box-shadow: var(--shadow); }
.modal-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: rgba(2, 6, 23, .55); }
.modal { width: min(560px, 100%); padding: 28px; position: relative; border-radius: 18px; background: var(--surface); box-shadow: var(--shadow); }
.modal h2 { margin-top: 0; }.modal p { color: var(--muted); line-height: 1.8; }
.modal-close { position: absolute; right: 14px; top: 14px; border: 0; background: none; font-size: 24px; cursor: pointer; }
@media (max-width: 980px) {
  .landing-grid, .review-grid { grid-template-columns: 1fr; }
  .review-workspace { height: auto; }
  .document-panel { min-height: 540px; }
  .issues-panel { min-height: 600px; }
  .layers { grid-template-columns: repeat(3, 1fr); }
  .stats-strip { grid-template-columns: repeat(3, 1fr); }
  .radar { display: none; }
}
@media (max-width: 680px) {
  .topbar { padding: 0 13px; }
  .brand small, .top-actions .compact, .top-actions .ghost { display: none; }
  .landing { padding: 18px 12px 30px; }
  .hero { padding: 28px 22px; }
  .hero h1 { font-size: 32px; }
  .landing-grid { grid-template-columns: minmax(0, 1fr); }
  .layers { grid-template-columns: repeat(2, 1fr); }
  .stats-strip { grid-template-columns: repeat(2, 1fr); }
  .review-toolbar { align-items: stretch; flex-direction: column; }
  .review-toolbar > div { overflow-x: auto; }
  .find-panel { flex-wrap: wrap; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; }
}
</style>
