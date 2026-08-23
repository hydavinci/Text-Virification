import type { CheckCategory } from './review'
import type { DocumentBlock } from './analysis'

export type DocumentViewMode = 'original' | 'modified' | 'diff'
export type DocumentVersionStatus = 'queued' | 'analyzing' | 'succeeded' | 'failed'

export interface DraftBlock {
  block_id: string
  text: string
}

export interface DocumentVersion {
  version_id: string
  job_id: string
  parent_version_id: string | null
  revision_number: number
  status: DocumentVersionStatus
  source_kind: string
  created_reason: string
  content_sha256: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  failure_code: string | null
  failure_message: string | null
}

export interface VersionListResponse {
  job_id: string
  active_version_id: string | null
  versions: DocumentVersion[]
}

export interface EditDraft {
  draft_id: string
  job_id: string
  base_version_id: string
  revision: number
  blocks: DraftBlock[]
  content_sha256: string | null
  created_at: string
  updated_at: string
  consumed_at: string | null
}

export interface UpdateDraftRequest {
  expected_revision: number
  blocks: DraftBlock[]
}

export interface ReanalyzeRequest {
  expected_draft_revision: number
  idempotency_key: string
}

export interface ReanalysisResponse {
  version: DocumentVersion
  events_url: string
}

export type DiffKind = 'equal' | 'insert' | 'delete'

export interface DiffSegment {
  kind: DiffKind
  text: string
}

export interface DerivedDiffBlock {
  block_id: string
  segments: DiffSegment[]
}

interface DerivedResponseFields {
  job_id: string
  version_id: string
  decision_snapshot_sha256: string
}

export interface ModifiedDerivedResponse extends DerivedResponseFields {
  blocks: DocumentBlock[]
}

export interface DiffDerivedResponse extends DerivedResponseFields {
  blocks: DerivedDiffBlock[]
}

export type DerivedResponse = ModifiedDerivedResponse | DiffDerivedResponse

export interface VersionEventMetadata {
  current_category: CheckCategory
  completed_categories: CheckCategory[]
  issue_count: number
}

export interface VersionEvent {
  sequence: number
  status: DocumentVersionStatus
  progress: number
  message: string
  created_at: string
  metadata: VersionEventMetadata | null
}

export type OperationType = 'decision' | 'undo'

export interface OperationBatch {
  batch_id: string
  job_id: string
  version_id: string
  operation_type: OperationType
  affected_count: number
  undoes_batch_id: string | null
  created_at: string
}

export interface OperationBatchPage {
  job_id: string
  version_id: string
  total: number
  items: OperationBatch[]
  next_cursor: string | null
}
