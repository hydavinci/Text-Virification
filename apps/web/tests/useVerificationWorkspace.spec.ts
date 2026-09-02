import { describe, expect, it } from 'vitest'

import { useVerificationWorkspace } from '../src/composables/useVerificationWorkspace'
import type {
  VerificationIssue,
  VerificationResult
} from '../src/types/verification'

const documentId = '11111111-1111-1111-1111-111111111111'
const runId = '22222222-2222-2222-2222-222222222222'
const sourceVersion = 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'

function buildIssue(overrides: Partial<VerificationIssue> = {}): VerificationIssue {
  return {
    issue_id: '33333333-3333-3333-3333-333333333333',
    document_id: documentId,
    verification_run_id: runId,
    block_id: 'p-0',
    page: null,
    start: 1,
    end: 2,
    block_start: 1,
    block_end: 2,
    type: 'typo',
    severity: 'warning',
    original: '乙',
    suggestion: 'B',
    alternatives: ['B'],
    layer: 'character',
    message: '疑似错别字',
    description: '疑似错别字',
    rule_id: 'cn_typo',
    rule_version: '1',
    source: 'test',
    source_version: sourceVersion,
    confidence: 0.8,
    auto_fixable: true,
    context: '甲乙丙丁',
    position: 99,
    end_position: 100,
    review: null,
    review_reason: null,
    ...overrides
  }
}

function buildResult(
  issues: VerificationIssue[],
  overrides: Partial<VerificationResult> = {}
): VerificationResult {
  const text = overrides.text ?? '甲乙丙丁'
  return {
    success: true,
    filename: 'sample.txt',
    source_name: 'sample.txt',
    file_type: 'txt',
    text,
    blocks: [
      {
        block_id: 'p-0',
        kind: 'paragraph',
        text,
        global_start: 0,
        global_end: text.length,
        block_start: 0,
        block_end: text.length,
        page: null,
        paragraph_index: 0,
        table_index: null,
        row_index: null,
        cell_index: null,
        bbox: null,
        parent_id: null,
        style: {},
        source_locator: { paragraph_index: 0 }
      }
    ],
    parser_name: 'compatibility-flat-text',
    parser_version: '1',
    stats: {
      char_count: text.length,
      char_count_no_space: text.length,
      line_count: 1,
      paragraph_count: 1,
      language: 'zh',
      primary_count: text.length,
      primary_label: '总字数'
    },
    issues,
    summary: {
      total: issues.length,
      by_type: { typo: issues.length },
      by_severity: { warning: issues.length },
      by_rule: { cn_typo: issues.length },
      by_layer: { character: issues.length }
    },
    file_id: null,
    file_ext: null,
    document_id: documentId,
    verification_run_id: runId,
    source_version: sourceVersion,
    execution_mode: 'synchronous',
    analysis_mode: 'local_only',
    dictionary_versions: {},
    degradation: {
      is_degraded: false,
      reasons: []
    },
    scenario: 'general',
    ...overrides
  }
}

describe('useVerificationWorkspace', () => {
  it('keeps decisions and selected suggestions attached to issue ids after reordering', () => {
    const issueA = buildIssue()
    const issueB = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: '丙',
      suggestion: 'C'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issueA, issueB]))
    workspace.acceptIssue(issueA.issue_id)
    workspace.selectSuggestion(issueA.issue_id, '乙方')
    workspace.loadResult(buildResult([issueB, issueA]))

    expect(workspace.issueStates.value[issueA.issue_id]).toBe('accepted')
    expect(workspace.selectedSuggestions.value[issueA.issue_id]).toBe('乙方')
    expect(workspace.modifiedText.value).toBe('甲乙方丙丁')
  })

  it('prunes absent issue ids on the same source revision', () => {
    const issueA = buildIssue()
    const issueB = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: '丙',
      suggestion: 'C'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issueA, issueB]))
    workspace.acceptIssues([issueA.issue_id, issueB.issue_id])
    workspace.loadResult(buildResult([issueB]))

    expect(workspace.issueStates.value).toEqual({ [issueB.issue_id]: 'accepted' })
    expect(workspace.selectedSuggestions.value).toEqual({ [issueB.issue_id]: 'C' })
  })

  it.each([
    {
      label: 'document',
      result: buildResult([buildIssue()], {
        document_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        issues: [
          buildIssue({
            document_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
          })
        ]
      })
    },
    {
      label: 'source revision',
      result: buildResult([buildIssue()], {
        source_version: 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        issues: [
          buildIssue({
            source_version: 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
          })
        ]
      })
    }
  ])('resets review state for a different $label', ({ result }) => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)

    workspace.loadResult(result)

    expect(workspace.issueStates.value).toEqual({})
  })

  it('applies accepted replacements in descending canonical offset order', () => {
    const first = buildIssue({
      start: 1,
      end: 2,
      block_start: 1,
      block_end: 2,
      original: '乙',
      suggestion: 'FIRST'
    })
    const second = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 3,
      end: 4,
      block_start: 3,
      block_end: 4,
      original: '丁',
      suggestion: 'SECOND'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([first, second]))
    workspace.acceptIssues([first.issue_id, second.issue_id])

    expect(workspace.modifiedText.value).toBe('甲FIRST丙SECOND')
  })

  it('applies deletion suggestions', () => {
    const issue = buildIssue({
      start: 0,
      end: 2,
      block_start: 0,
      block_end: 2,
      original: '删除',
      suggestion: ''
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue], { text: '删除保留文本' }))
    workspace.acceptIssue(issue.issue_id)

    expect(workspace.modifiedText.value).toBe('保留文本')
  })

  it('does not automatically replace a null suggestion', () => {
    const issue = buildIssue({ suggestion: null, auto_fixable: false })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)

    expect(workspace.issueStates.value[issue.issue_id]).toBe('accepted')
    expect(workspace.modifiedText.value).toBe('甲乙丙丁')
  })

  it('uses canonical start and end while safely ignoring stale or invalid issues', () => {
    const valid = buildIssue({ position: -50, end_position: -25 })
    const staleDocument = buildIssue({
      issue_id: '40000000-0000-0000-0000-000000000001',
      document_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    })
    const staleRun = buildIssue({
      issue_id: '40000000-0000-0000-0000-000000000002',
      verification_run_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    })
    const staleSource = buildIssue({
      issue_id: '40000000-0000-0000-0000-000000000003',
      source_version: 'sha256:stale'
    })
    const outOfRange = buildIssue({
      issue_id: '40000000-0000-0000-0000-000000000004',
      start: 3,
      end: 8,
      block_start: 3,
      block_end: 8,
      original: '丁'
    })
    const mismatchedOriginal = buildIssue({
      issue_id: '40000000-0000-0000-0000-000000000005',
      original: '甲'
    })
    const fractionalOffset = buildIssue({
      issue_id: '40000000-0000-0000-0000-000000000006',
      start: 1.5
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([
      staleDocument,
      staleRun,
      staleSource,
      outOfRange,
      mismatchedOriginal,
      fractionalOffset,
      valid
    ]))
    workspace.acceptIssues([
      staleDocument.issue_id,
      staleRun.issue_id,
      staleSource.issue_id,
      outOfRange.issue_id,
      mismatchedOriginal.issue_id,
      fractionalOffset.issue_id,
      valid.issue_id
    ])

    expect(workspace.visibleIssues.value.map((issue) => issue.issue_id)).toEqual([valid.issue_id])
    expect(workspace.issueStates.value).toEqual({ [valid.issue_id]: 'accepted' })
    expect(workspace.modifiedText.value).toBe('甲B丙丁')
  })

  it('ignores overlapping issues deterministically regardless of input order', () => {
    const earlier = buildIssue({
      issue_id: '40000000-0000-0000-0000-000000000001',
      start: 1,
      end: 4,
      block_start: 1,
      block_end: 4,
      original: 'bcd',
      suggestion: 'X',
      context: 'abcdef'
    })
    const later = buildIssue({
      issue_id: '40000000-0000-0000-0000-000000000002',
      start: 2,
      end: 5,
      block_start: 2,
      block_end: 5,
      original: 'cde',
      suggestion: 'Y',
      context: 'abcdef'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([later, earlier], { text: 'abcdef' }))
    workspace.acceptIssues([later.issue_id, earlier.issue_id])

    expect(workspace.visibleIssues.value.map((issue) => issue.issue_id)).toEqual([earlier.issue_id])
    expect(workspace.modifiedText.value).toBe('aXef')
  })

  it('restores exact prior batch state including absence versus explicit pending', () => {
    const issueA = buildIssue()
    const issueB = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: '丙',
      suggestion: 'C'
    })
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issueA, issueB]))
    workspace.issueStates.value[issueB.issue_id] = 'pending'

    workspace.acceptIssues([issueA.issue_id, issueB.issue_id])
    workspace.undoLastBatch()

    expect(Object.hasOwn(workspace.issueStates.value, issueA.issue_id)).toBe(false)
    expect(Object.hasOwn(workspace.issueStates.value, issueB.issue_id)).toBe(true)
    expect(workspace.issueStates.value[issueB.issue_id]).toBe('pending')
  })

  it('supports individual accept, reject, and undo with stable-id summary counts', () => {
    const issueA = buildIssue()
    const issueB = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: '丙',
      suggestion: 'C'
    })
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issueA, issueB]))

    workspace.acceptIssue(issueA.issue_id)
    workspace.rejectIssue(issueB.issue_id)
    expect(workspace.summary.value).toEqual({
      total: 2,
      pending: 0,
      accepted: 1,
      rejected: 1
    })

    workspace.undoIssue(issueA.issue_id)
    expect(workspace.summary.value).toEqual({
      total: 2,
      pending: 1,
      accepted: 0,
      rejected: 1
    })
  })

  it('creates immutable manual revisions and invalidates source-bound decisions', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)
    const reviewRevision = workspace.currentRevision.value

    workspace.saveManualEdit('手工修改后的全文')

    expect(reviewRevision?.text).toBe('甲B丙丁')
    expect(workspace.currentRevision.value).toMatchObject({
      document_id: documentId,
      source_version: sourceVersion,
      parent_revision_id: reviewRevision?.revision_id,
      kind: 'manual',
      text: '手工修改后的全文'
    })
    expect(workspace.currentRevision.value?.revision_id).toBeTruthy()
    expect(Object.isFrozen(workspace.currentRevision.value)).toBe(true)
    expect(workspace.requiresReverification.value).toBe(true)
    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.selectedSuggestions.value).toEqual({})
    expect(workspace.modifiedText.value).toBe('手工修改后的全文')
  })
})
