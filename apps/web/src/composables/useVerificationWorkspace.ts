import { computed, ref, shallowRef, toRaw } from 'vue'

import type {
  BoundingBox,
  DocumentRevision,
  IssueState,
  JsonValue,
  OcrRequirement,
  PdfDocumentMetadata,
  PdfExtractionWarning,
  PdfImage,
  PdfPageMetadata,
  PdfTable,
  PdfTableCell,
  PdfTextCharacter,
  PdfTextSpan,
  TextBlock,
  VerificationIssue,
  VerificationResult,
  VerificationStats,
  VerificationSummary,
  WorkspaceReviewSummary
} from '../types/verification'

interface BatchStateSnapshot {
  documentId: string
  verificationRunId: string
  sourceVersion: string
  entries: Record<string, PriorIssueState>
}

interface Utf16Range {
  start: number
  end: number
}

export interface WorkspaceReviewStateRestore {
  documentId: string
  verificationRunId: string
  sourceVersion: string
  issueStates: unknown
  selectedSuggestions: unknown
}

type PriorIssueState =
  | { hadValue: false }
  | { hadValue: true; value: IssueState }

export interface WorkspaceReadonlyValue<T> {
  readonly __v_isRef: true
  readonly value: T
}

function workspaceReadonlyValue<T>(
  readValue: () => T
): WorkspaceReadonlyValue<T> {
  const facade: WorkspaceReadonlyValue<T> = {
    __v_isRef: true,
    get value(): T {
      return readValue()
    }
  }
  return Object.freeze(facade)
}

function hasOwn<T extends object>(value: T, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function recordEntries(value: unknown): [string, unknown][] {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? Object.entries(value)
    : []
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nullRecord<T>(): Record<string, T> {
  return Object.create(null) as Record<string, T>
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value
  )
}

function isIssueState(value: unknown): value is IssueState {
  return value === 'pending' || value === 'accepted' || value === 'rejected'
}

function isInteger(value: number | null): value is number {
  return value !== null && Number.isInteger(value)
}

function codePointLength(value: string): number {
  return Array.from(value).length
}

function freezeRecursively<T>(value: T): T {
  if (
    value === null ||
    (typeof value !== 'object' && typeof value !== 'function')
  ) {
    return value
  }
  for (const key of Reflect.ownKeys(value)) {
    freezeRecursively(Reflect.get(value, key))
  }
  return Object.freeze(value)
}

function utf16IndexAtCodePointOffset(
  value: string,
  codePointOffset: number
): number | null {
  if (!Number.isInteger(codePointOffset) || codePointOffset < 0) {
    return null
  }

  let currentCodePointOffset = 0
  let currentUtf16Index = 0
  for (const character of value) {
    if (currentCodePointOffset === codePointOffset) {
      return currentUtf16Index
    }
    currentCodePointOffset += 1
    currentUtf16Index += character.length
  }
  return currentCodePointOffset === codePointOffset ? currentUtf16Index : null
}

function utf16RangeForCodePointOffsets(
  value: string,
  start: number,
  end: number
): Utf16Range | null {
  if (
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end < start
  ) {
    return null
  }

  const utf16Start = utf16IndexAtCodePointOffset(value, start)
  const utf16End = utf16IndexAtCodePointOffset(value, end)
  if (utf16Start === null || utf16End === null) {
    return null
  }
  return {
    start: utf16Start,
    end: utf16End
  }
}

function sliceCodePointRange(
  value: string,
  start: number,
  end: number
): string | null {
  const range = utf16RangeForCodePointOffsets(value, start, end)
  return range === null ? null : value.slice(range.start, range.end)
}

function replaceCodePointRange(
  value: string,
  start: number,
  end: number,
  replacement: string
): string | null {
  const range = utf16RangeForCodePointOffsets(value, start, end)
  if (range === null) {
    return null
  }
  return `${value.slice(0, range.start)}${replacement}${value.slice(range.end)}`
}

function hasCanonicalBlocks(result: VerificationResult): boolean {
  const blocksById = new Map<string, TextBlock>()
  const documentLength = codePointLength(result.text)

  for (const block of result.blocks) {
    if (
      typeof block.block_id !== 'string' ||
      blocksById.has(block.block_id) ||
      (block.parent_id !== null && typeof block.parent_id !== 'string')
    ) {
      return false
    }
    const offsets = [
      block.global_start,
      block.global_end,
      block.block_start,
      block.block_end
    ]
    if (
      offsets.some((offset) => !Number.isInteger(offset) || offset < 0) ||
      block.global_end < block.global_start ||
      block.block_end < block.block_start
    ) {
      return false
    }
    const blockLength = codePointLength(block.text)
    if (
      block.global_end - block.global_start !== blockLength ||
      block.block_end - block.block_start !== blockLength ||
      block.block_start !== 0 ||
      block.block_end !== blockLength ||
      block.global_end > documentLength ||
      sliceCodePointRange(
        result.text,
        block.global_start,
        block.global_end
      ) !== block.text
    ) {
      return false
    }
    blocksById.set(block.block_id, block)
  }

  for (const block of result.blocks) {
    if (block.parent_id === null) {
      continue
    }
    const parent = blocksById.get(block.parent_id)
    if (
      parent === undefined ||
      parent.block_id === block.block_id ||
      parent.global_start > block.global_start ||
      block.global_end > parent.global_end
    ) {
      return false
    }
  }

  const ancestorsById = new Map<string, ReadonlySet<string>>()
  for (const block of result.blocks) {
    const visited = new Set([block.block_id])
    const ancestors = new Set<string>()
    let parentId = block.parent_id
    while (parentId !== null) {
      if (visited.has(parentId)) {
        return false
      }
      const parent = blocksById.get(parentId)
      if (parent === undefined) {
        return false
      }
      visited.add(parentId)
      ancestors.add(parentId)
      parentId = parent.parent_id
    }
    ancestorsById.set(block.block_id, ancestors)
  }

  for (let firstIndex = 0; firstIndex < result.blocks.length; firstIndex += 1) {
    const first = result.blocks[firstIndex]
    for (
      let secondIndex = firstIndex + 1;
      secondIndex < result.blocks.length;
      secondIndex += 1
    ) {
      const second = result.blocks[secondIndex]
      if (
        first.global_start >= second.global_end ||
        second.global_start >= first.global_end
      ) {
        continue
      }
      if (
        ancestorsById.get(first.block_id)?.has(second.block_id) ||
        ancestorsById.get(second.block_id)?.has(first.block_id)
      ) {
        continue
      }
      return false
    }
  }
  return true
}

function isCanonicalIssue(
  issue: VerificationIssue,
  result: VerificationResult,
  blocksById: ReadonlyMap<string, VerificationResult['blocks'][number]>
): boolean {
  if (
    !issue.issue_id ||
    issue.document_id !== result.document_id ||
    issue.verification_run_id !== result.verification_run_id ||
    !Number.isInteger(issue.start) ||
    !Number.isInteger(issue.end) ||
    issue.start < 0 ||
    issue.end <= issue.start ||
    issue.end - issue.start !== codePointLength(issue.original) ||
    sliceCodePointRange(result.text, issue.start, issue.end) !== issue.original
  ) {
    return false
  }

  if (issue.block_id === null) {
    return issue.block_start === null && issue.block_end === null
  }

  const block = blocksById.get(issue.block_id)
  if (
    block === undefined ||
    !isInteger(issue.block_start) ||
    !isInteger(issue.block_end) ||
    issue.block_end <= issue.block_start ||
    issue.block_end - issue.block_start !== issue.end - issue.start ||
    issue.start < block.global_start ||
    issue.end > block.global_end
  ) {
    return false
  }

  const expectedBlockStart = block.block_start + issue.start - block.global_start
  const expectedBlockEnd = block.block_start + issue.end - block.global_start
  const localStart = issue.block_start - block.block_start
  const localEnd = issue.block_end - block.block_start
  return (
    issue.block_start === expectedBlockStart &&
    issue.block_end === expectedBlockEnd &&
    sliceCodePointRange(block.text, localStart, localEnd) === issue.original
  )
}

function canonicalIssues(
  result: VerificationResult
): readonly VerificationIssue[] {
  if (!hasCanonicalBlocks(result)) {
    return Object.freeze([])
  }
  const blocksById = new Map(result.blocks.map((block) => [block.block_id, block]))
  const candidates = result.issues
    .filter((issue) => isCanonicalIssue(issue, result, blocksById))
    .sort((left, right) =>
      left.start - right.start ||
      left.end - right.end ||
      left.issue_id.localeCompare(right.issue_id) ||
      JSON.stringify(left).localeCompare(JSON.stringify(right))
    )
  const accepted: VerificationIssue[] = []
  const seenIds = new Set<string>()

  for (const issue of candidates) {
    if (seenIds.has(issue.issue_id)) {
      continue
    }
    accepted.push(issue)
    seenIds.add(issue.issue_id)
  }
  return Object.freeze(accepted)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isNullableNonnegativeInteger(
  value: unknown
): value is number | null {
  return value === null || isNonnegativeInteger(value)
}

function copyJsonValue(value: unknown): JsonValue | undefined {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    isFiniteNumber(value)
  ) {
    return value
  }
  if (Array.isArray(value)) {
    const copied: JsonValue[] = []
    for (const entry of value) {
      const next = copyJsonValue(entry)
      if (next === undefined) {
        return undefined
      }
      copied.push(next)
    }
    return copied
  }
  if (!isRecord(value)) {
    return undefined
  }
  const copied = nullRecord<JsonValue>()
  for (const [key, entry] of Object.entries(value)) {
    const next = copyJsonValue(entry)
    if (next === undefined) {
      return undefined
    }
    copied[key] = next
  }
  return copied
}

function copyJsonRecord(value: unknown): Record<string, JsonValue> | null {
  const copied = copyJsonValue(value)
  return copied !== undefined &&
    !Array.isArray(copied) &&
    copied !== null &&
    typeof copied === 'object'
    ? copied
    : null
}

function copyStringRecord(value: unknown): Record<string, string> | null {
  if (!isRecord(value)) {
    return null
  }
  const copied = nullRecord<string>()
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry !== 'string') {
      return null
    }
    copied[key] = entry
  }
  return copied
}

function copyCountRecord(value: unknown): Record<string, number> | null {
  if (!isRecord(value)) {
    return null
  }
  const copied = nullRecord<number>()
  for (const [key, entry] of Object.entries(value)) {
    if (!isNonnegativeInteger(entry)) {
      return null
    }
    copied[key] = entry
  }
  return copied
}

function copyStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== 'string')) {
    return null
  }
  return value.map((entry) => String(entry))
}

function copyBoundingBox(value: unknown): BoundingBox | null | undefined {
  if (value === null) {
    return null
  }
  if (
    !Array.isArray(value) ||
    value.length !== 4 ||
    !value.every(isFiniteNumber)
  ) {
    return undefined
  }
  return [value[0], value[1], value[2], value[3]]
}

function copyTextBlock(value: unknown): TextBlock | null {
  if (!isRecord(value)) {
    return null
  }
  const kinds = new Set([
    'paragraph',
    'heading',
    'table_cell',
    'header',
    'footer',
    'image'
  ])
  const bbox = copyBoundingBox(value.bbox)
  const style = copyJsonRecord(value.style)
  const sourceLocator = copyJsonRecord(value.source_locator)
  if (
    typeof value.block_id !== 'string' ||
    typeof value.kind !== 'string' ||
    !kinds.has(value.kind) ||
    typeof value.text !== 'string' ||
    !isNonnegativeInteger(value.global_start) ||
    !isNonnegativeInteger(value.global_end) ||
    !isNonnegativeInteger(value.block_start) ||
    !isNonnegativeInteger(value.block_end) ||
    !isNullableNonnegativeInteger(value.page) ||
    !isNullableNonnegativeInteger(value.paragraph_index) ||
    !isNullableNonnegativeInteger(value.table_index) ||
    !isNullableNonnegativeInteger(value.row_index) ||
    !isNullableNonnegativeInteger(value.cell_index) ||
    bbox === undefined ||
    (value.parent_id !== null && typeof value.parent_id !== 'string') ||
    style === null ||
    sourceLocator === null
  ) {
    return null
  }
  return {
    block_id: value.block_id,
    kind: value.kind as TextBlock['kind'],
    text: value.text,
    global_start: value.global_start,
    global_end: value.global_end,
    block_start: value.block_start,
    block_end: value.block_end,
    page: value.page,
    paragraph_index: value.paragraph_index,
    table_index: value.table_index,
    row_index: value.row_index,
    cell_index: value.cell_index,
    bbox,
    parent_id: value.parent_id,
    style,
    source_locator: sourceLocator
  }
}

function copyVerificationIssue(value: unknown): VerificationIssue | null {
  if (!isRecord(value)) {
    return null
  }
  const alternatives =
    value.alternatives === undefined || value.alternatives === null
      ? value.alternatives
      : copyStringArray(value.alternatives)
  if (
    typeof value.issue_id !== 'string' ||
    !isUuid(value.issue_id) ||
    typeof value.document_id !== 'string' ||
    !isUuid(value.document_id) ||
    typeof value.verification_run_id !== 'string' ||
    !isUuid(value.verification_run_id) ||
    (value.block_id !== null && typeof value.block_id !== 'string') ||
    !isNullableNonnegativeInteger(value.page) ||
    !isNonnegativeInteger(value.start) ||
    !isNonnegativeInteger(value.end) ||
    !isNullableNonnegativeInteger(value.block_start) ||
    !isNullableNonnegativeInteger(value.block_end) ||
    typeof value.type !== 'string' ||
    (value.severity !== 'error' &&
      value.severity !== 'warning' &&
      value.severity !== 'info') ||
    typeof value.original !== 'string' ||
    (value.suggestion !== null && typeof value.suggestion !== 'string') ||
    (alternatives !== undefined &&
      alternatives !== null &&
      !Array.isArray(alternatives)) ||
    typeof value.layer !== 'string' ||
    typeof value.message !== 'string' ||
    typeof value.description !== 'string' ||
    typeof value.rule_id !== 'string' ||
    typeof value.rule_version !== 'string' ||
    typeof value.source !== 'string' ||
    typeof value.source_version !== 'string' ||
    !isFiniteNumber(value.confidence) ||
    typeof value.auto_fixable !== 'boolean' ||
    typeof value.context !== 'string' ||
    !isNonnegativeInteger(value.position) ||
    !isNonnegativeInteger(value.end_position) ||
    (value.review !== undefined &&
      value.review !== null &&
      typeof value.review !== 'string') ||
    (value.review_reason !== undefined &&
      value.review_reason !== null &&
      typeof value.review_reason !== 'string')
  ) {
    return null
  }
  return {
    issue_id: value.issue_id,
    document_id: value.document_id,
    verification_run_id: value.verification_run_id,
    block_id: value.block_id,
    page: value.page,
    start: value.start,
    end: value.end,
    block_start: value.block_start,
    block_end: value.block_end,
    type: value.type,
    severity: value.severity,
    original: value.original,
    suggestion: value.suggestion,
    alternatives:
      alternatives === undefined ? undefined : alternatives,
    layer: value.layer,
    message: value.message,
    description: value.description,
    rule_id: value.rule_id,
    rule_version: value.rule_version,
    source: value.source,
    source_version: value.source_version,
    confidence: value.confidence,
    auto_fixable: value.auto_fixable,
    context: value.context,
    position: value.position,
    end_position: value.end_position,
    review: value.review as string | null | undefined,
    review_reason: value.review_reason as string | null | undefined
  }
}

function copyVerificationStats(value: unknown): VerificationStats | null {
  if (
    !isRecord(value) ||
    !isNonnegativeInteger(value.char_count) ||
    !isNonnegativeInteger(value.char_count_no_space) ||
    !isNonnegativeInteger(value.line_count) ||
    !isNonnegativeInteger(value.paragraph_count) ||
    (value.language !== 'zh' && value.language !== 'en') ||
    !isNonnegativeInteger(value.primary_count) ||
    typeof value.primary_label !== 'string'
  ) {
    return null
  }
  return {
    char_count: value.char_count,
    char_count_no_space: value.char_count_no_space,
    line_count: value.line_count,
    paragraph_count: value.paragraph_count,
    language: value.language,
    primary_count: value.primary_count,
    primary_label: value.primary_label
  }
}

function copyVerificationSummary(
  value: unknown
): VerificationSummary | null {
  if (!isRecord(value) || !isNonnegativeInteger(value.total)) {
    return null
  }
  const byType = copyCountRecord(value.by_type)
  const bySeverity = copyCountRecord(value.by_severity)
  const byRule = copyCountRecord(value.by_rule)
  const byLayer = copyCountRecord(value.by_layer)
  const llmReview =
    value.llm_review === undefined
      ? undefined
      : copyJsonRecord(value.llm_review)
  if (
    byType === null ||
    bySeverity === null ||
    byRule === null ||
    byLayer === null ||
    llmReview === null
  ) {
    return null
  }
  return {
    total: value.total,
    by_type: byType,
    by_severity: bySeverity,
    by_rule: byRule,
    by_layer: byLayer,
    ...(llmReview === undefined ? {} : { llm_review: llmReview })
  }
}

function copyOcrRequirement(value: unknown): OcrRequirement | null {
  if (
    !isRecord(value) ||
    (value.mode !== 'required' && value.mode !== 'partial') ||
    !Array.isArray(value.pages) ||
    !value.pages.every(isNonnegativeInteger)
  ) {
    return null
  }
  return {
    mode: value.mode,
    pages: [...value.pages]
  }
}

function copyDirection(value: unknown): [number, number] | null {
  return Array.isArray(value) &&
    value.length === 2 &&
    value.every(isFiniteNumber)
    ? [value[0], value[1]]
    : null
}

function copyPdfTextCharacter(value: unknown): PdfTextCharacter | null {
  if (!isRecord(value)) {
    return null
  }
  const bbox = copyBoundingBox(value.bbox)
  const lineDirection = copyDirection(value.line_direction)
  if (
    typeof value.text !== 'string' ||
    bbox === undefined ||
    !isNonnegativeInteger(value.source_start) ||
    !isNonnegativeInteger(value.source_end) ||
    !['glyph', 'glyphless', 'synthetic_space', 'unmapped'].includes(
      String(value.mapping_state)
    ) ||
    (value.group_id !== null && typeof value.group_id !== 'string') ||
    lineDirection === null ||
    (value.writing_mode !== 0 && value.writing_mode !== 1) ||
    !isNonnegativeInteger(value.raw_line_index) ||
    (value.span_order !== null && !isNonnegativeInteger(value.span_order))
  ) {
    return null
  }
  return {
    text: value.text,
    bbox,
    source_start: value.source_start,
    source_end: value.source_end,
    mapping_state:
      value.mapping_state as PdfTextCharacter['mapping_state'],
    group_id: value.group_id,
    line_direction: lineDirection,
    writing_mode: value.writing_mode,
    raw_line_index: value.raw_line_index,
    span_order: value.span_order
  }
}

function copyPdfTextSpan(value: unknown): PdfTextSpan | null {
  if (!isRecord(value)) {
    return null
  }
  const bbox = copyBoundingBox(value.bbox)
  const lineDirection = copyDirection(value.line_direction)
  if (
    typeof value.text !== 'string' ||
    bbox === null ||
    bbox === undefined ||
    typeof value.font_name !== 'string' ||
    !isFiniteNumber(value.font_size) ||
    !isNonnegativeInteger(value.font_flags) ||
    !isNonnegativeInteger(value.color) ||
    !isNonnegativeInteger(value.span_index) ||
    !Array.isArray(value.characters) ||
    lineDirection === null ||
    (value.writing_mode !== 0 && value.writing_mode !== 1) ||
    !isNonnegativeInteger(value.line_index) ||
    !isNonnegativeInteger(value.span_order)
  ) {
    return null
  }
  const characters = value.characters.map(copyPdfTextCharacter)
  if (characters.some((entry) => entry === null)) {
    return null
  }
  return {
    text: value.text,
    bbox,
    font_name: value.font_name,
    font_size: value.font_size,
    font_flags: value.font_flags,
    color: value.color,
    span_index: value.span_index,
    characters: characters as PdfTextCharacter[],
    line_direction: lineDirection,
    writing_mode: value.writing_mode,
    line_index: value.line_index,
    span_order: value.span_order
  }
}

function copyPdfTableCell(value: unknown): PdfTableCell | null {
  if (!isRecord(value)) {
    return null
  }
  const bbox = copyBoundingBox(value.bbox)
  if (
    typeof value.text !== 'string' ||
    bbox === undefined ||
    !isNonnegativeInteger(value.table_index) ||
    !isNonnegativeInteger(value.row_index) ||
    !isNonnegativeInteger(value.cell_index) ||
    !Array.isArray(value.characters)
  ) {
    return null
  }
  const characters = value.characters.map(copyPdfTextCharacter)
  if (characters.some((entry) => entry === null)) {
    return null
  }
  return {
    text: value.text,
    bbox,
    table_index: value.table_index,
    row_index: value.row_index,
    cell_index: value.cell_index,
    characters: characters as PdfTextCharacter[]
  }
}

function copyPdfTable(value: unknown): PdfTable | null {
  if (!isRecord(value)) {
    return null
  }
  const bbox = copyBoundingBox(value.bbox)
  if (
    !isNonnegativeInteger(value.table_index) ||
    bbox === null ||
    bbox === undefined ||
    !isNonnegativeInteger(value.row_count) ||
    !isNonnegativeInteger(value.column_count) ||
    !Array.isArray(value.rows)
  ) {
    return null
  }
  const rows: PdfTableCell[][] = []
  for (const row of value.rows) {
    if (!Array.isArray(row)) {
      return null
    }
    const cells = row.map(copyPdfTableCell)
    if (cells.some((entry) => entry === null)) {
      return null
    }
    rows.push(cells as PdfTableCell[])
  }
  return {
    table_index: value.table_index,
    bbox,
    row_count: value.row_count,
    column_count: value.column_count,
    rows
  }
}

function copyPdfImage(value: unknown): PdfImage | null {
  if (!isRecord(value)) {
    return null
  }
  const bbox = copyBoundingBox(value.bbox)
  if (
    !isNonnegativeInteger(value.image_index) ||
    !isNonnegativeInteger(value.xref) ||
    bbox === null ||
    bbox === undefined
  ) {
    return null
  }
  return {
    image_index: value.image_index,
    xref: value.xref,
    bbox
  }
}

function copyPdfPageMetadata(value: unknown): PdfPageMetadata | null {
  if (!isRecord(value)) {
    return null
  }
  const pageBbox = copyBoundingBox(value.page_bbox)
  if (
    !isNonnegativeInteger(value.page) ||
    !['text', 'scanned', 'mixed'].includes(String(value.kind)) ||
    pageBbox === null ||
    pageBbox === undefined ||
    !isNonnegativeInteger(value.text_length) ||
    !isFiniteNumber(value.text_density) ||
    !isFiniteNumber(value.image_coverage) ||
    typeof value.ocr_required !== 'boolean' ||
    !Array.isArray(value.spans) ||
    !Array.isArray(value.tables) ||
    !Array.isArray(value.images)
  ) {
    return null
  }
  const spans = value.spans.map(copyPdfTextSpan)
  const tables = value.tables.map(copyPdfTable)
  const images = value.images.map(copyPdfImage)
  if (
    spans.some((entry) => entry === null) ||
    tables.some((entry) => entry === null) ||
    images.some((entry) => entry === null)
  ) {
    return null
  }
  return {
    page: value.page,
    kind: value.kind as PdfPageMetadata['kind'],
    page_bbox: pageBbox,
    text_length: value.text_length,
    text_density: value.text_density,
    image_coverage: value.image_coverage,
    ocr_required: value.ocr_required,
    spans: spans as PdfTextSpan[],
    tables: tables as PdfTable[],
    images: images as PdfImage[]
  }
}

function copyPdfWarning(value: unknown): PdfExtractionWarning | null {
  if (
    !isRecord(value) ||
    !isNonnegativeInteger(value.page) ||
    !['table', 'image', 'ocr'].includes(String(value.stage)) ||
    ![
      'pdf_table_extraction_failed',
      'pdf_image_extraction_failed',
      'pdf_ocr_no_text'
    ].includes(String(value.code)) ||
    typeof value.message !== 'string'
  ) {
    return null
  }
  return {
    page: value.page,
    stage: value.stage as PdfExtractionWarning['stage'],
    code: value.code as PdfExtractionWarning['code'],
    message: value.message
  }
}

function copyPdfMetadata(value: unknown): PdfDocumentMetadata | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value.pages) ||
    !Array.isArray(value.warnings)
  ) {
    return null
  }
  const pages = value.pages.map(copyPdfPageMetadata)
  const warnings = value.warnings.map(copyPdfWarning)
  const requirement =
    value.ocr_requirement === null
      ? null
      : copyOcrRequirement(value.ocr_requirement)
  if (
    pages.some((entry) => entry === null) ||
    warnings.some((entry) => entry === null) ||
    (value.ocr_requirement !== null && requirement === null)
  ) {
    return null
  }
  return {
    pages: pages as PdfPageMetadata[],
    warnings: warnings as PdfExtractionWarning[],
    ocr_requirement: requirement
  }
}

function canonicalResultSnapshot(value: unknown): VerificationResult | null {
  if (!isRecord(value)) {
    return null
  }
  const fileTypes = new Set(['docx', 'doc', 'pdf', 'txt', 'rtf', 'md', 'csv'])
  const scenarios = new Set([
    'general',
    'academic',
    'business',
    'legal',
    'news',
    'technical'
  ])
  const stats = copyVerificationStats(value.stats)
  const summary = copyVerificationSummary(value.summary)
  const dictionaryVersions = copyStringRecord(value.dictionary_versions)
  const reasons =
    isRecord(value.degradation) && Array.isArray(value.degradation.reasons)
      ? copyStringArray(value.degradation.reasons)
      : null
  if (
    value.success !== true ||
    typeof value.filename !== 'string' ||
    typeof value.source_name !== 'string' ||
    typeof value.file_type !== 'string' ||
    !fileTypes.has(value.file_type) ||
    typeof value.text !== 'string' ||
    !Array.isArray(value.blocks) ||
    typeof value.parser_name !== 'string' ||
    typeof value.parser_version !== 'string' ||
    stats === null ||
    !Array.isArray(value.issues) ||
    summary === null ||
    (value.file_id !== null &&
      (typeof value.file_id !== 'string' || !isUuid(value.file_id))) ||
    (value.file_ext !== null && typeof value.file_ext !== 'string') ||
    typeof value.document_id !== 'string' ||
    !isUuid(value.document_id) ||
    typeof value.verification_run_id !== 'string' ||
    !isUuid(value.verification_run_id) ||
    typeof value.source_version !== 'string' ||
    (value.execution_mode !== 'synchronous' &&
      value.execution_mode !== 'asynchronous') ||
    (value.analysis_mode !== 'local_only' &&
      value.analysis_mode !== 'local_plus_llm') ||
    dictionaryVersions === null ||
    !isRecord(value.degradation) ||
    typeof value.degradation.is_degraded !== 'boolean' ||
    reasons === null ||
    typeof value.scenario !== 'string' ||
    !scenarios.has(value.scenario)
  ) {
    return null
  }

  const blocks = value.blocks.map(copyTextBlock)
  const issues = value.issues.map(copyVerificationIssue)
  if (
    blocks.some((entry) => entry === null) ||
    issues.some((entry) => entry === null)
  ) {
    return null
  }
  const pdfMetadata =
    value.pdf_metadata === undefined
      ? undefined
      : copyPdfMetadata(value.pdf_metadata)
  const ocrRequirement =
    value.ocr_requirement === undefined
      ? undefined
      : value.ocr_requirement === null
        ? null
        : copyOcrRequirement(value.ocr_requirement)
  if (
    (value.pdf_metadata !== undefined && pdfMetadata === null) ||
    (value.ocr_requirement !== undefined &&
      value.ocr_requirement !== null &&
      ocrRequirement === null)
  ) {
    return null
  }

  const result: VerificationResult = {
    success: true,
    filename: value.filename,
    source_name: value.source_name,
    file_type: value.file_type as VerificationResult['file_type'],
    text: value.text,
    blocks: blocks as TextBlock[],
    parser_name: value.parser_name,
    parser_version: value.parser_version,
    stats,
    issues: issues as VerificationIssue[],
    summary,
    file_id: value.file_id,
    file_ext: value.file_ext,
    document_id: value.document_id,
    verification_run_id: value.verification_run_id,
    source_version: value.source_version,
    execution_mode: value.execution_mode,
    analysis_mode: value.analysis_mode,
    dictionary_versions: dictionaryVersions,
    degradation: {
      is_degraded: value.degradation.is_degraded,
      reasons
    },
    scenario: value.scenario as VerificationResult['scenario']
  }
  if (pdfMetadata !== undefined && pdfMetadata !== null) {
    result.pdf_metadata = pdfMetadata
  }
  if (ocrRequirement !== undefined) {
    result.ocr_requirement = ocrRequirement
  }
  if (
    !hasCanonicalBlocks(result) ||
    canonicalIssues(result).length !== result.issues.length ||
    result.issues.some(
      (issue) =>
        issue.document_id !== result.document_id ||
        issue.verification_run_id !== result.verification_run_id
    )
  ) {
    return null
  }
  return freezeRecursively(result)
}

function sourceRevision(result: VerificationResult): Readonly<DocumentRevision> {
  return Object.freeze({
    revision_id: null,
    document_id: result.document_id,
    verification_run_id: result.verification_run_id,
    source_version: result.source_version,
    revision_number: null,
    created_at: null,
    parent_revision_id: null,
    persistence_state: 'source',
    kind: 'source',
    text: result.text
  })
}

function restoredRevision(
  value: unknown,
  result: VerificationResult
): Readonly<DocumentRevision> | null {
  const revision = isRecord(value) ? value : null
  if (
    revision !== null &&
    revision.revision_id === null &&
    revision.revision_number === null &&
    revision.created_at === null &&
    revision.parent_revision_id === null &&
    revision.persistence_state === 'source' &&
    revision.kind === 'source' &&
    revision.document_id === result.document_id &&
    revision.verification_run_id === result.verification_run_id &&
    revision.source_version === result.source_version &&
    revision.text === result.text
  ) {
    return sourceRevision(result)
  }
  if (
    revision === null ||
    typeof revision.revision_id !== 'string' ||
    !isUuid(revision.revision_id) ||
    revision.document_id !== result.document_id ||
    revision.verification_run_id !== result.verification_run_id ||
    revision.source_version !== result.source_version ||
    typeof revision.created_at !== 'string' ||
    (revision.parent_revision_id !== null &&
      (typeof revision.parent_revision_id !== 'string' ||
        !isUuid(revision.parent_revision_id))) ||
    revision.parent_revision_id === revision.revision_id ||
    (revision.kind !== 'review' && revision.kind !== 'manual') ||
    typeof revision.text !== 'string'
  ) {
    return null
  }
  if (
    (revision.persistence_state === 'draft' &&
      revision.revision_number !== null) ||
    (revision.persistence_state === 'persisted' &&
      (!Number.isInteger(revision.revision_number) ||
        Number(revision.revision_number) <= 0)) ||
    (revision.persistence_state !== 'draft' &&
      revision.persistence_state !== 'persisted')
  ) {
    return null
  }
  const createdAt = new Date(revision.created_at)
  if (
    Number.isNaN(createdAt.valueOf()) ||
    createdAt.toISOString() !== revision.created_at
  ) {
    return null
  }
  return freezeRecursively({
    revision_id: revision.revision_id,
    document_id: result.document_id,
    verification_run_id: result.verification_run_id,
    source_version: result.source_version,
    revision_number:
      revision.persistence_state === 'persisted'
        ? Number(revision.revision_number)
        : null,
    created_at: revision.created_at,
    parent_revision_id: revision.parent_revision_id,
    persistence_state: revision.persistence_state,
    kind: revision.kind,
    text: revision.text
  } as DocumentRevision)
}

interface PreparedWorkspaceRestore {
  result: VerificationResult
  safeIssues: readonly VerificationIssue[]
  issueStates: Record<string, IssueState>
  selectedSuggestions: Record<string, string | null>
  currentRevision: Readonly<DocumentRevision>
  requiresReverification: boolean
}

function restoredStableState(
  value: unknown,
  validIds: ReadonlySet<string>
): Record<string, IssueState> | null {
  if (!isRecord(value)) {
    return null
  }
  const restored = nullRecord<IssueState>()
  for (const [issueId, state] of Object.entries(value)) {
    if (validIds.has(issueId) && isIssueState(state)) {
      restored[issueId] = state
    }
  }
  return restored
}

function restoredSuggestions(
  value: unknown,
  validIds: ReadonlySet<string>
): Record<string, string | null> | null {
  if (!isRecord(value)) {
    return null
  }
  const restored = nullRecord<string | null>()
  for (const [issueId, suggestion] of Object.entries(value)) {
    if (
      validIds.has(issueId) &&
      (typeof suggestion === 'string' || suggestion === null)
    ) {
      restored[issueId] = suggestion
    }
  }
  return restored
}

function restoredSuggestion(
  issue: VerificationIssue,
  suggestions: Readonly<Record<string, string | null>>
): string | null {
  return hasOwn(suggestions, issue.issue_id)
    ? suggestions[issue.issue_id]
    : issue.suggestion
}

function restoredReplacementConflicts(
  issues: readonly VerificationIssue[],
  states: Readonly<Record<string, IssueState>>,
  suggestions: Readonly<Record<string, string | null>>
): boolean {
  const accepted = issues
    .filter((issue) => states[issue.issue_id] === 'accepted')
    .filter((issue) => restoredSuggestion(issue, suggestions) !== null)
  return accepted.some((left, index) =>
    accepted
      .slice(index + 1)
      .some((right) => left.start < right.end && right.start < left.end)
  )
}

function restoredReviewText(
  result: VerificationResult,
  issues: readonly VerificationIssue[],
  states: Readonly<Record<string, IssueState>>,
  suggestions: Readonly<Record<string, string | null>>
): string {
  let text = result.text
  const accepted = issues
    .filter((issue) => states[issue.issue_id] === 'accepted')
    .filter((issue) => restoredSuggestion(issue, suggestions) !== null)
    .sort((left, right) =>
      right.start - left.start ||
      right.end - left.end ||
      right.issue_id.localeCompare(left.issue_id)
    )
  for (const issue of accepted) {
    const suggestion = restoredSuggestion(issue, suggestions)
    if (suggestion === null) {
      continue
    }
    const replaced = replaceCodePointRange(
      text,
      issue.start,
      issue.end,
      suggestion
    )
    if (replaced !== null) {
      text = replaced
    }
  }
  return text
}

function legacyReviewRevision(
  result: VerificationResult,
  text: string
): Readonly<DocumentRevision> {
  if (text === result.text) {
    return sourceRevision(result)
  }
  return Object.freeze({
    revision_id: globalThis.crypto.randomUUID(),
    document_id: result.document_id,
    verification_run_id: result.verification_run_id,
    source_version: result.source_version,
    revision_number: null,
    created_at: new Date().toISOString(),
    parent_revision_id: null,
    persistence_state: 'draft',
    kind: 'review',
    text
  })
}

function prepareWorkspaceRestore(
  saved: unknown
): PreparedWorkspaceRestore | null {
  if (!isRecord(saved) || !hasOwn(saved, 'result')) {
    return null
  }
  const result = canonicalResultSnapshot(saved.result)
  if (result === null) {
    return null
  }
  const safeIssues = canonicalIssues(result)
  const validIds = new Set(safeIssues.map((issue) => issue.issue_id))
  const issueStates = restoredStableState(saved.issueStates, validIds)
  const selectedSuggestions = restoredSuggestions(
    saved.selectedSuggestions,
    validIds
  )
  if (issueStates === null || selectedSuggestions === null) {
    return null
  }

  if (!hasOwn(saved, 'version')) {
    if (typeof saved.workingText !== 'string') {
      return null
    }
    if (saved.workingText !== result.text) {
      return {
        result,
        safeIssues,
        issueStates: nullRecord<IssueState>(),
        selectedSuggestions: nullRecord<string | null>(),
        currentRevision: Object.freeze({
          revision_id: globalThis.crypto.randomUUID(),
          document_id: result.document_id,
          verification_run_id: result.verification_run_id,
          source_version: result.source_version,
          revision_number: null,
          created_at: new Date().toISOString(),
          parent_revision_id: null,
          persistence_state: 'draft',
          kind: 'manual',
          text: saved.workingText
        }),
        requiresReverification: true
      }
    }
    const conflicts = restoredReplacementConflicts(
      safeIssues,
      issueStates,
      selectedSuggestions
    )
    const text = restoredReviewText(
      result,
      safeIssues,
      issueStates,
      selectedSuggestions
    )
    return {
      result,
      safeIssues,
      issueStates,
      selectedSuggestions,
      currentRevision: conflicts
        ? sourceRevision(result)
        : legacyReviewRevision(result, text),
      requiresReverification: false
    }
  }

  if (
    saved.version !== 2 ||
    typeof saved.requiresReverification !== 'boolean' ||
    !hasOwn(saved, 'currentRevision')
  ) {
    return null
  }
  const currentRevision = restoredRevision(saved.currentRevision, result)
  if (currentRevision === null) {
    return null
  }
  if (saved.requiresReverification) {
    if (currentRevision.kind !== 'manual') {
      return null
    }
    return {
      result,
      safeIssues,
      issueStates: nullRecord<IssueState>(),
      selectedSuggestions: nullRecord<string | null>(),
      currentRevision,
      requiresReverification: true
    }
  }
  if (currentRevision.kind === 'manual') {
    return null
  }
  const conflicts = restoredReplacementConflicts(
    safeIssues,
    issueStates,
    selectedSuggestions
  )
  const expectedText = restoredReviewText(
    result,
    safeIssues,
    issueStates,
    selectedSuggestions
  )
  if (
    (!conflicts && currentRevision.text !== expectedText) ||
    (!conflicts &&
      currentRevision.kind === 'source' &&
      expectedText !== result.text)
  ) {
    return null
  }
  return {
    result,
    safeIssues,
    issueStates,
    selectedSuggestions,
    currentRevision,
    requiresReverification: false
  }
}

export function useVerificationWorkspace() {
  const result = shallowRef<VerificationResult | null>(null)
  const issueStates = ref<Record<string, IssueState>>({})
  const selectedSuggestions = ref<Record<string, string | null>>({})
  const safeIssues = shallowRef<readonly VerificationIssue[]>(Object.freeze([]))
  const currentRevision = shallowRef<Readonly<DocumentRevision> | null>(null)
  const requiresReverification = ref(false)
  const batchHistory = ref<BatchStateSnapshot[]>([])

  const visibleIssues = computed<readonly VerificationIssue[]>(() =>
    requiresReverification.value ? Object.freeze([]) : safeIssues.value
  )

  function issueIds(): Set<string> {
    return new Set(safeIssues.value.map((issue) => issue.issue_id))
  }

  function applyAcceptedReplacements(): string {
    const currentResult = result.value
    if (currentResult === null) {
      return ''
    }

    let text = currentResult.text
    const acceptedIssues = safeIssues.value
      .filter((issue) => issueStates.value[issue.issue_id] === 'accepted')
      .filter((issue) => effectiveSuggestion(issue) !== null)
      .sort((left, right) =>
        right.start - left.start ||
        right.end - left.end ||
        right.issue_id.localeCompare(left.issue_id)
      )

    for (const issue of acceptedIssues) {
      const suggestion = effectiveSuggestion(issue)
      if (suggestion === null) {
        continue
      }
      const replaced = replaceCodePointRange(
        text,
        issue.start,
        issue.end,
        suggestion
      )
      if (replaced !== null) {
        text = replaced
      }
    }
    return text
  }

  function effectiveSuggestion(issue: VerificationIssue): string | null {
    return hasOwn(selectedSuggestions.value, issue.issue_id)
      ? selectedSuggestions.value[issue.issue_id]
      : issue.suggestion
  }

  const replacementConflictIssueIds = computed(() => {
    const acceptedIssues = safeIssues.value
      .filter((issue) => issueStates.value[issue.issue_id] === 'accepted')
      .filter((issue) => effectiveSuggestion(issue) !== null)
    const conflictingIds = new Set<string>()

    for (let leftIndex = 0; leftIndex < acceptedIssues.length; leftIndex += 1) {
      const left = acceptedIssues[leftIndex]
      for (
        let rightIndex = leftIndex + 1;
        rightIndex < acceptedIssues.length;
        rightIndex += 1
      ) {
        const right = acceptedIssues[rightIndex]
        if (left.start < right.end && right.start < left.end) {
          conflictingIds.add(left.issue_id)
          conflictingIds.add(right.issue_id)
        }
      }
    }

    return Object.freeze(
      acceptedIssues
        .filter((issue) => conflictingIds.has(issue.issue_id))
        .map((issue) => issue.issue_id)
    )
  })

  const hasReplacementConflicts = computed(
    () => replacementConflictIssueIds.value.length > 0
  )

  const modifiedText = computed(() => {
    if (
      (requiresReverification.value || hasReplacementConflicts.value) &&
      currentRevision.value !== null
    ) {
      return currentRevision.value.text
    }
    return applyAcceptedReplacements()
  })

  const summary = computed<WorkspaceReviewSummary>(() => {
    const counts: WorkspaceReviewSummary = {
      total: visibleIssues.value.length,
      pending: 0,
      accepted: 0,
      rejected: 0
    }
    for (const issue of visibleIssues.value) {
      const state = issueStates.value[issue.issue_id] ?? 'pending'
      counts[state] += 1
    }
    return Object.freeze(counts)
  })

  function createReviewRevision(): void {
    const currentResult = result.value
    if (
      currentResult === null ||
      requiresReverification.value ||
      hasReplacementConflicts.value
    ) {
      return
    }
    const text = applyAcceptedReplacements()
    const priorRevision = currentRevision.value
    if (
      priorRevision !== null &&
      priorRevision.document_id === currentResult.document_id &&
      priorRevision.verification_run_id === currentResult.verification_run_id &&
      priorRevision.source_version === currentResult.source_version &&
      priorRevision.kind !== 'manual' &&
      priorRevision.text === text
    ) {
      return
    }
    if (
      text === currentResult.text &&
      (priorRevision === null || priorRevision.persistence_state === 'source')
    ) {
      currentRevision.value = sourceRevision(currentResult)
      return
    }
    currentRevision.value = Object.freeze({
      revision_id: globalThis.crypto.randomUUID(),
      document_id: currentResult.document_id,
      verification_run_id: currentResult.verification_run_id,
      source_version: currentResult.source_version,
      revision_number: null,
      created_at: new Date().toISOString(),
      parent_revision_id: priorRevision?.revision_id ?? null,
      persistence_state: 'draft',
      kind: 'review',
      text
    })
  }

  function loadResult(nextResult: VerificationResult): void {
    const canonicalResult = freezeRecursively(structuredClone(toRaw(nextResult)))
    const priorResult = result.value
    const sameSourceRevision =
      !requiresReverification.value &&
      priorResult !== null &&
      priorResult.document_id === canonicalResult.document_id &&
      priorResult.source_version === canonicalResult.source_version &&
      priorResult.verification_run_id === canonicalResult.verification_run_id
    const nextIssues = canonicalIssues(canonicalResult)
    const nextIds = new Set(nextIssues.map((issue) => issue.issue_id))
    const nextStates: Record<string, IssueState> = {}
    const nextSuggestions: Record<string, string | null> = {}

    if (sameSourceRevision) {
      for (const issueId of nextIds) {
        if (hasOwn(issueStates.value, issueId)) {
          nextStates[issueId] = issueStates.value[issueId]
        }
        if (hasOwn(selectedSuggestions.value, issueId)) {
          nextSuggestions[issueId] = selectedSuggestions.value[issueId]
        }
      }
    }

    result.value = canonicalResult
    safeIssues.value = nextIssues
    issueStates.value = nextStates
    selectedSuggestions.value = nextSuggestions
    requiresReverification.value = false
    batchHistory.value = []
    if (!sameSourceRevision) {
      currentRevision.value = sourceRevision(canonicalResult)
      return
    }
    createReviewRevision()
  }

  function clearResult(): void {
    result.value = null
    safeIssues.value = Object.freeze([])
    issueStates.value = {}
    selectedSuggestions.value = {}
    currentRevision.value = null
    requiresReverification.value = false
    batchHistory.value = []
  }

  function setIssueState(issueId: string, state: IssueState): void {
    if (requiresReverification.value || !issueIds().has(issueId)) {
      return
    }
    issueStates.value = {
      ...issueStates.value,
      [issueId]: state
    }
    createReviewRevision()
  }

  function acceptIssue(issueId: string): void {
    setIssueState(issueId, 'accepted')
  }

  function rejectIssue(issueId: string): void {
    setIssueState(issueId, 'rejected')
  }

  function undoIssue(issueId: string): void {
    if (requiresReverification.value || !issueIds().has(issueId)) {
      return
    }
    const nextStates = { ...issueStates.value }
    delete nextStates[issueId]
    issueStates.value = nextStates
    createReviewRevision()
  }

  function setIssueStates(issueIdsToUpdate: string[], state: IssueState): void {
    const currentResult = result.value
    if (currentResult === null || requiresReverification.value) {
      return
    }
    const validIds = issueIds()
    const requestedIds = [...new Set(issueIdsToUpdate)].filter((issueId) =>
      validIds.has(issueId)
    )
    if (requestedIds.length === 0) {
      return
    }

    const entries: Record<string, PriorIssueState> = {}
    const nextStates = { ...issueStates.value }
    for (const issueId of requestedIds) {
      entries[issueId] = hasOwn(issueStates.value, issueId)
        ? { hadValue: true, value: issueStates.value[issueId] }
        : { hadValue: false }
      nextStates[issueId] = state
    }
    batchHistory.value.push({
      documentId: currentResult.document_id,
      verificationRunId: currentResult.verification_run_id,
      sourceVersion: currentResult.source_version,
      entries
    })
    issueStates.value = nextStates
    createReviewRevision()
  }

  function acceptIssues(issueIdsToAccept: string[]): void {
    setIssueStates(issueIdsToAccept, 'accepted')
  }

  function rejectIssues(issueIdsToReject: string[]): void {
    setIssueStates(issueIdsToReject, 'rejected')
  }

  function undoLastBatch(): void {
    const currentResult = result.value
    const snapshot = batchHistory.value.pop()
    if (
      currentResult === null ||
      snapshot === undefined ||
      snapshot.documentId !== currentResult.document_id ||
      snapshot.verificationRunId !== currentResult.verification_run_id ||
      snapshot.sourceVersion !== currentResult.source_version
    ) {
      return
    }

    const nextStates = { ...issueStates.value }
    for (const [issueId, priorState] of Object.entries(snapshot.entries)) {
      if (priorState.hadValue) {
        nextStates[issueId] = priorState.value
      } else {
        delete nextStates[issueId]
      }
    }
    issueStates.value = nextStates
    createReviewRevision()
  }

  function selectSuggestion(issueId: string, suggestion: string | null): void {
    if (requiresReverification.value || !issueIds().has(issueId)) {
      return
    }
    selectedSuggestions.value = {
      ...selectedSuggestions.value,
      [issueId]: suggestion
    }
    createReviewRevision()
  }

  function restoreReviewState(saved: WorkspaceReviewStateRestore): void {
    const currentResult = result.value
    if (
      currentResult === null ||
      requiresReverification.value ||
      saved.documentId !== currentResult.document_id ||
      saved.verificationRunId !== currentResult.verification_run_id ||
      saved.sourceVersion !== currentResult.source_version
    ) {
      return
    }

    const validIds = issueIds()
    const nextStates: Record<string, IssueState> = {}
    const nextSuggestions: Record<string, string | null> = {}

    for (const [issueId, state] of recordEntries(saved.issueStates)) {
      if (validIds.has(issueId) && isIssueState(state)) {
        nextStates[issueId] = state
      }
    }
    for (const [issueId, suggestion] of recordEntries(
      saved.selectedSuggestions
    )) {
      if (
        validIds.has(issueId) &&
        (typeof suggestion === 'string' || suggestion === null)
      ) {
        nextSuggestions[issueId] = suggestion
      }
    }

    issueStates.value = nextStates
    selectedSuggestions.value = nextSuggestions
    batchHistory.value = []
    createReviewRevision()
  }

  function restoreWorkspaceState(saved: unknown): boolean {
    const prepared = prepareWorkspaceRestore(saved)
    if (prepared === null) {
      return false
    }
    result.value = prepared.result
    safeIssues.value = prepared.safeIssues
    issueStates.value = prepared.issueStates
    selectedSuggestions.value = prepared.selectedSuggestions
    currentRevision.value = prepared.currentRevision
    requiresReverification.value = prepared.requiresReverification
    batchHistory.value = []
    return true
  }

  function saveManualEdit(text: string): Readonly<DocumentRevision> | null {
    const currentResult = result.value
    if (currentResult === null) {
      return null
    }
    const priorRevision = currentRevision.value ?? sourceRevision(currentResult)
    if (text === priorRevision.text) {
      return null
    }
    const revision = Object.freeze({
      revision_id: globalThis.crypto.randomUUID(),
      document_id: currentResult.document_id,
      verification_run_id: currentResult.verification_run_id,
      source_version: currentResult.source_version,
      revision_number: null,
      created_at: new Date().toISOString(),
      parent_revision_id: priorRevision.revision_id,
      persistence_state: 'draft' as const,
      kind: 'manual' as const,
      text
    })
    currentRevision.value = revision
    requiresReverification.value = true
    issueStates.value = {}
    selectedSuggestions.value = {}
    batchHistory.value = []
    return revision
  }

  const issueStateSnapshots = computed(() =>
    Object.freeze({ ...issueStates.value })
  )
  const selectedSuggestionSnapshots = computed(() =>
    Object.freeze({ ...selectedSuggestions.value })
  )

  return {
    result: workspaceReadonlyValue(() => result.value),
    issueStates: workspaceReadonlyValue(() => issueStateSnapshots.value),
    selectedSuggestions: workspaceReadonlyValue(
      () => selectedSuggestionSnapshots.value
    ),
    currentRevision: workspaceReadonlyValue(() => currentRevision.value),
    requiresReverification: workspaceReadonlyValue(
      () => requiresReverification.value
    ),
    modifiedText: workspaceReadonlyValue(() => modifiedText.value),
    visibleIssues: workspaceReadonlyValue(() => visibleIssues.value),
    summary: workspaceReadonlyValue(() => summary.value),
    replacementConflictIssueIds: workspaceReadonlyValue(
      () => replacementConflictIssueIds.value
    ),
    hasReplacementConflicts: workspaceReadonlyValue(
      () => hasReplacementConflicts.value
    ),
    canUndoLastBatch: workspaceReadonlyValue(
      () => batchHistory.value.length > 0
    ),
    loadResult,
    clearResult,
    setIssueState,
    acceptIssue,
    rejectIssue,
    undoIssue,
    setIssueStates,
    acceptIssues,
    rejectIssues,
    undoLastBatch,
    selectSuggestion,
    restoreReviewState,
    restoreWorkspaceState,
    saveManualEdit
  }
}
