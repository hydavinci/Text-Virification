export type Scenario = 'general' | 'academic' | 'business' | 'legal' | 'news' | 'technical'
export type IssueSeverity = 'error' | 'warning' | 'info'
export type IssueState = 'pending' | 'accepted' | 'rejected'
export type VerificationExecutionMode = 'synchronous' | 'asynchronous'
export type VerificationAnalysisMode = 'local_only' | 'local_plus_llm'
export type FileType = 'docx' | 'doc' | 'pdf' | 'txt' | 'rtf' | 'md' | 'csv'
export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue }
export type BoundingBox = [number, number, number, number]

export interface GlossaryTerm {
  original: string
  standard: string
}

export interface VerificationIssue {
  issue_id: string
  document_id: string
  verification_run_id: string
  block_id: string | null
  page: number | null
  start: number
  end: number
  block_start: number | null
  block_end: number | null
  type: string
  severity: IssueSeverity
  original: string
  suggestion: string | null
  alternatives?: string[] | null
  layer: string
  message: string
  description: string
  rule_id: string
  rule_version: string
  source: string
  source_version: string
  confidence: number
  auto_fixable: boolean
  context: string
  /** @deprecated Compatibility alias. Use start. */
  position: number
  /** @deprecated Compatibility alias. Use end. */
  end_position: number
  review?: string | null
  review_reason?: string | null
}

export interface VerificationDegradation {
  is_degraded: boolean
  reasons: string[]
}

export interface TextBlock {
  block_id: string
  kind: 'paragraph' | 'heading' | 'table_cell' | 'header' | 'footer' | 'image'
  text: string
  global_start: number
  global_end: number
  block_start: number
  block_end: number
  page: number | null
  paragraph_index: number | null
  table_index: number | null
  row_index: number | null
  cell_index: number | null
  bbox: BoundingBox | null
  parent_id: string | null
  style: Record<string, JsonValue>
  source_locator: Record<string, JsonValue>
}

export type PdfPageKind = 'text' | 'scanned' | 'mixed'
export type PdfCharacterMappingState = 'glyph' | 'glyphless' | 'synthetic_space' | 'unmapped'
export type PdfWritingMode = 0 | 1

export interface PdfExtractionWarning {
  page: number
  stage: 'table' | 'image' | 'ocr'
  code: 'pdf_table_extraction_failed' | 'pdf_image_extraction_failed' | 'pdf_ocr_no_text'
  message: string
}

export interface PdfTextCharacter {
  text: string
  bbox: BoundingBox | null
  source_start: number
  source_end: number
  mapping_state: PdfCharacterMappingState
  group_id: string | null
  line_direction: [number, number]
  writing_mode: PdfWritingMode
  raw_line_index: number
  span_order: number | null
}

export interface PdfTextSpan {
  text: string
  bbox: BoundingBox
  font_name: string
  font_size: number
  font_flags: number
  color: number
  span_index: number
  characters: PdfTextCharacter[]
  line_direction: [number, number]
  writing_mode: PdfWritingMode
  line_index: number
  span_order: number
}

export interface PdfTableCell {
  text: string
  bbox: BoundingBox | null
  table_index: number
  row_index: number
  cell_index: number
  characters: PdfTextCharacter[]
}

export interface PdfTable {
  table_index: number
  bbox: BoundingBox
  row_count: number
  column_count: number
  rows: PdfTableCell[][]
}

export interface PdfImage {
  image_index: number
  xref: number
  bbox: BoundingBox
}

export interface OcrRequirement {
  mode: 'required' | 'partial'
  pages: number[]
}

export interface PdfPageMetadata {
  page: number
  kind: PdfPageKind
  page_bbox: BoundingBox
  text_length: number
  text_density: number
  image_coverage: number
  ocr_required: boolean
  spans: PdfTextSpan[]
  tables: PdfTable[]
  images: PdfImage[]
}

export interface PdfDocumentMetadata {
  pages: PdfPageMetadata[]
  warnings: PdfExtractionWarning[]
  ocr_requirement: OcrRequirement | null
}

export interface VerificationStats {
  char_count: number
  char_count_no_space: number
  line_count: number
  paragraph_count: number
  language: 'zh' | 'en'
  primary_count: number
  primary_label: string
}

export interface VerificationSummary {
  total: number
  by_type: Record<string, number>
  by_severity: Record<string, number>
  by_rule: Record<string, number>
  by_layer: Record<string, number>
  llm_review?: Record<string, JsonValue>
}

export interface VerificationResult {
  success: boolean
  filename: string
  source_name: string
  file_type: FileType
  text: string
  blocks: TextBlock[]
  parser_name: string
  parser_version: string
  stats: VerificationStats
  issues: VerificationIssue[]
  summary: VerificationSummary
  file_id: string | null
  file_ext: string | null
  document_id: string
  verification_run_id: string
  source_version: string
  execution_mode: VerificationExecutionMode
  analysis_mode: VerificationAnalysisMode
  dictionary_versions: Record<string, string>
  degradation: VerificationDegradation
  scenario: Scenario
  pdf_metadata?: PdfDocumentMetadata
  ocr_requirement?: OcrRequirement | null
}

export type DocumentRevisionKind = 'source' | 'review' | 'manual'
export type DocumentRevisionPersistenceState = 'source' | 'draft' | 'persisted'

interface DocumentRevisionBase {
  document_id: string
  verification_run_id: string
  source_version: string
  text: string
}

export interface SourceDocumentRevision extends DocumentRevisionBase {
  revision_id: null
  revision_number: null
  created_at: null
  parent_revision_id: null
  persistence_state: 'source'
  kind: 'source'
}

interface AuthoredDocumentRevision extends DocumentRevisionBase {
  revision_id: string
  created_at: string
  parent_revision_id: string | null
  kind: 'review' | 'manual'
}

export interface DraftDocumentRevision extends AuthoredDocumentRevision {
  revision_number: null
  persistence_state: 'draft'
}

export interface PersistedDocumentRevision extends AuthoredDocumentRevision {
  /** Positive per-run sequence allocated by the backend. */
  revision_number: number
  persistence_state: 'persisted'
}

export type DocumentRevision =
  | SourceDocumentRevision
  | DraftDocumentRevision
  | PersistedDocumentRevision

export interface WorkspaceReviewSummary {
  total: number
  pending: number
  accepted: number
  rejected: number
}

export interface AnalyzeOptions {
  scenario: Scenario
  enableSecurity: boolean
  enableSensitive: boolean
  enableAdExtreme: boolean
  glossary: GlossaryTerm[]
  bannedWords: string[]
}

export interface ExportReplacement {
  original: string
  suggestion: string
  position: number
  end_position: number
}

export interface RecheckProvenance {
  grant: string
  result_document_id: string
  result_verification_run_id: string
  result_source_version: string
}

export interface ExportArtifactReference {
  export_artifact_id: string
  job_id: string
  verification_run_id: string
  format: 'docx_reconstruction' | 'original_format'
  file_type: FileType
  file_name: string
  media_type: string
  size_bytes: number
  content_sha256: string
  status: 'ready'
  created_at: string
}
