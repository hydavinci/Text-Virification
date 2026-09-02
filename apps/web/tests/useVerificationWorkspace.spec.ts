import { describe, expect, it } from 'vitest'

import { useVerificationWorkspace } from '../src/composables/useVerificationWorkspace'
import type {
  PersistedDocumentRevision,
  VerificationIssue,
  VerificationResult
} from '../src/types/verification'

const documentId = '11111111-1111-1111-1111-111111111111'
const runId = '22222222-2222-2222-2222-222222222222'
const sourceVersion = 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

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
    source_version: '1',
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
  const codePointLength = Array.from(text).length
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
        global_end: codePointLength,
        block_start: 0,
        block_end: codePointLength,
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
      char_count: codePointLength,
      char_count_no_space: codePointLength,
      line_count: 1,
      paragraph_count: 1,
      language: 'zh',
      primary_count: codePointLength,
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
    expect(workspace.selectedSuggestions.value).toEqual({})
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
        source_version: 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
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

  it('resets decisions and overrides for a new verification run with stable issue ids', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)
    workspace.selectSuggestion(issue.issue_id, '显式替换')

    const nextRunId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    workspace.loadResult(buildResult([
      buildIssue({ verification_run_id: nextRunId })
    ], {
      verification_run_id: nextRunId
    }))

    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.selectedSuggestions.value).toEqual({})
    expect(workspace.currentRevision.value).toMatchObject({
      kind: 'source',
      verification_run_id: nextRunId,
      revision_id: null,
      persistence_state: 'source',
      revision_number: null
    })
  })

  it('accepts production-shaped checker source versions independent of document source versions', () => {
    const issue = buildIssue({ source_version: '1' })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue], { source_version: sourceVersion }))
    workspace.acceptIssue(issue.issue_id)

    expect(workspace.visibleIssues.value).toEqual([issue])
    expect(workspace.modifiedText.value).toBe('甲B丙丁')
  })

  it('applies non-overlapping replacements in descending canonical code-point order with astral text', () => {
    const first = buildIssue({
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: '乙',
      suggestion: 'FIRST'
    })
    const second = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 4,
      end: 5,
      block_start: 4,
      block_end: 5,
      original: '丁',
      suggestion: 'SECOND'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([first, second], { text: '甲😀乙丙丁' }))
    workspace.acceptIssues([first.issue_id, second.issue_id])

    expect(workspace.modifiedText.value).toBe('甲😀FIRST丙SECOND')
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

  it('uses updated backend defaults for untouched suggestions on same-result reload', () => {
    const issue = buildIssue({ suggestion: '旧默认值' })
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)

    workspace.loadResult(buildResult([
      buildIssue({ suggestion: '新默认值' })
    ]))

    expect(workspace.selectedSuggestions.value).toEqual({})
    expect(workspace.modifiedText.value).toBe('甲新默认值丙丁')
  })

  it('preserves explicit suggestion overrides on same-result reload', () => {
    const issue = buildIssue({ suggestion: '旧默认值' })
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)
    workspace.selectSuggestion(issue.issue_id, '用户选择')

    workspace.loadResult(buildResult([
      buildIssue({ suggestion: '新默认值' })
    ]))

    expect(workspace.selectedSuggestions.value).toEqual({
      [issue.issue_id]: '用户选择'
    })
    expect(workspace.modifiedText.value).toBe('甲用户选择丙丁')
  })

  it.each([
    {
      label: 'null',
      override: null,
      expectedText: '甲乙丙丁'
    },
    {
      label: 'empty string',
      override: '',
      expectedText: '甲丙丁'
    }
  ])('preserves an explicit $label suggestion override on reload', ({
    override,
    expectedText
  }) => {
    const issue = buildIssue({ suggestion: '旧默认值' })
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)
    workspace.selectSuggestion(issue.issue_id, override)

    workspace.loadResult(buildResult([
      buildIssue({ suggestion: '新默认值' })
    ]))

    expect(workspace.selectedSuggestions.value).toEqual({
      [issue.issue_id]: override
    })
    expect(workspace.modifiedText.value).toBe(expectedText)
  })

  it('validates block-local canonical offsets after an astral character and replaces them', () => {
    const text = '前😀块乙后'
    const issue = buildIssue({
      start: 3,
      end: 4,
      block_start: 2,
      block_end: 3,
      original: '乙',
      suggestion: 'B'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue], {
      text,
      blocks: [
        {
          block_id: 'p-0',
          kind: 'paragraph',
          text: '😀块乙',
          global_start: 1,
          global_end: 4,
          block_start: 0,
          block_end: 3,
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
      ]
    }))
    workspace.acceptIssue(issue.issue_id)

    expect(workspace.visibleIssues.value).toEqual([issue])
    expect(workspace.modifiedText.value).toBe('前😀块B后')
  })

  it('validates and replaces an astral original using canonical code-point offsets', () => {
    const issue = buildIssue({
      start: 1,
      end: 2,
      block_start: 1,
      block_end: 2,
      original: '😀',
      suggestion: '表情'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue], { text: '甲😀乙' }))
    workspace.acceptIssue(issue.issue_id)

    expect(workspace.visibleIssues.value).toEqual([issue])
    expect(workspace.modifiedText.value).toBe('甲表情乙')
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
      outOfRange,
      mismatchedOriginal,
      fractionalOffset,
      valid
    ]))
    workspace.acceptIssues([
      staleDocument.issue_id,
      staleRun.issue_id,
      outOfRange.issue_id,
      mismatchedOriginal.issue_id,
      fractionalOffset.issue_id,
      valid.issue_id
    ])

    expect(workspace.visibleIssues.value.map((issue) => issue.issue_id)).toEqual([valid.issue_id])
    expect(workspace.issueStates.value).toEqual({ [valid.issue_id]: 'accepted' })
    expect(workspace.modifiedText.value).toBe('甲B丙丁')
  })

  it.each([
    ['forward', false],
    ['reversed', true]
  ])('preserves and counts overlapping issues in %s input order', (_label, reversed) => {
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

    workspace.loadResult(buildResult(
      reversed ? [later, earlier] : [earlier, later],
      { text: 'abcdef' }
    ))

    expect(workspace.visibleIssues.value.map((issue) => issue.issue_id)).toEqual([
      earlier.issue_id,
      later.issue_id
    ])
    expect(workspace.summary.value).toEqual({
      total: 2,
      pending: 2,
      accepted: 0,
      rejected: 0
    })
  })

  it.each([
    ['rejecting', 'rejectIssue'],
    ['undoing', 'undoIssue']
  ] as const)(
    '%s a conflicting accepted replacement clears the conflict and resumes revisions',
    (_label, resolveConflict) => {
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

      workspace.acceptIssue(earlier.issue_id)
      const lastValidRevision = workspace.currentRevision.value
      expect(lastValidRevision).toMatchObject({
        persistence_state: 'draft',
        kind: 'review',
        revision_number: null,
        text: 'aXef'
      })

      workspace.acceptIssue(later.issue_id)

      expect(workspace.replacementConflictIssueIds.value).toEqual([
        earlier.issue_id,
        later.issue_id
      ])
      expect(workspace.hasReplacementConflicts.value).toBe(true)
      expect(workspace.currentRevision.value).toBe(lastValidRevision)
      expect(workspace.modifiedText.value).toBe('aXef')

      workspace[resolveConflict](later.issue_id)
      expect(workspace.replacementConflictIssueIds.value).toEqual([])
      expect(workspace.hasReplacementConflicts.value).toBe(false)
      expect(workspace.currentRevision.value).toBe(lastValidRevision)

      workspace.selectSuggestion(earlier.issue_id, 'SAFE')
      expect(workspace.currentRevision.value).toMatchObject({
        persistence_state: 'draft',
        parent_revision_id: lastValidRevision?.revision_id,
        revision_number: null,
        text: 'aSAFEef'
      })
    }
  )

  it('fails closed when batch accepting conflicting replacements from the source revision', () => {
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
    const source = workspace.currentRevision.value

    workspace.acceptIssues([later.issue_id, earlier.issue_id])

    expect(workspace.replacementConflictIssueIds.value).toEqual([
      earlier.issue_id,
      later.issue_id
    ])
    expect(workspace.hasReplacementConflicts.value).toBe(true)
    expect(workspace.currentRevision.value).toBe(source)
    expect(workspace.modifiedText.value).toBe('abcdef')

    workspace.rejectIssue(later.issue_id)
    expect(workspace.hasReplacementConflicts.value).toBe(false)
    expect(workspace.currentRevision.value).toMatchObject({
      persistence_state: 'draft',
      parent_revision_id: null,
      revision_number: null,
      text: 'aXef'
    })
  })

  it('does not report overlap conflicts for accepted issues with an effective null suggestion', () => {
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
    workspace.selectSuggestion(later.issue_id, null)

    workspace.acceptIssues([later.issue_id, earlier.issue_id])

    expect(workspace.replacementConflictIssueIds.value).toEqual([])
    expect(workspace.hasReplacementConflicts.value).toBe(false)
    expect(workspace.currentRevision.value).toMatchObject({
      persistence_state: 'draft',
      revision_number: null,
      text: 'aXef'
    })
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
      verification_run_id: runId,
      source_version: sourceVersion,
      parent_revision_id: reviewRevision?.revision_id,
      persistence_state: 'draft',
      kind: 'manual',
      revision_number: null,
      text: '手工修改后的全文'
    })
    expect(workspace.currentRevision.value?.revision_id).toMatch(uuidPattern)
    expect(workspace.currentRevision.value?.created_at).toBe(
      new Date(workspace.currentRevision.value?.created_at ?? '').toISOString()
    )
    expect(Object.isFrozen(workspace.currentRevision.value)).toBe(true)
    expect(workspace.requiresReverification.value).toBe(true)
    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.selectedSuggestions.value).toEqual({})
    expect(workspace.modifiedText.value).toBe('手工修改后的全文')
  })

  it('distinguishes a non-persisted source from a serializable draft without inventing a number', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    const source = workspace.currentRevision.value

    expect(source).toEqual({
      revision_id: null,
      document_id: documentId,
      verification_run_id: runId,
      source_version: sourceVersion,
      revision_number: null,
      created_at: null,
      parent_revision_id: null,
      persistence_state: 'source',
      kind: 'source',
      text: '甲乙丙丁'
    })
    expect(Object.isFrozen(workspace.currentRevision.value)).toBe(true)

    workspace.acceptIssue(issue.issue_id)
    const reviewRevision = workspace.currentRevision.value

    expect(reviewRevision).toMatchObject({
      document_id: documentId,
      verification_run_id: runId,
      source_version: sourceVersion,
      persistence_state: 'draft',
      revision_number: null,
      parent_revision_id: null,
      kind: 'review',
      text: '甲B丙丁'
    })
    expect(reviewRevision?.revision_id).toMatch(uuidPattern)
    expect(reviewRevision?.created_at).toBe(
      new Date(reviewRevision?.created_at ?? '').toISOString()
    )
    expect(Object.isFrozen(reviewRevision)).toBe(true)
    expect(JSON.parse(JSON.stringify(reviewRevision))).toEqual(reviewRevision)
    expect(source?.persistence_state).toBe('source')
    expect(reviewRevision?.persistence_state).toBe('draft')
  })

  it('generates distinct serializable UUID drafts across workspace instances without fake numbers', () => {
    const issue = buildIssue()
    const first = useVerificationWorkspace()
    const second = useVerificationWorkspace()
    first.loadResult(buildResult([issue]))
    second.loadResult(buildResult([issue]))

    first.acceptIssue(issue.issue_id)
    second.acceptIssue(issue.issue_id)

    expect(first.currentRevision.value?.revision_id).toMatch(uuidPattern)
    expect(second.currentRevision.value?.revision_id).toMatch(uuidPattern)
    expect(first.currentRevision.value?.revision_id).not.toBe(
      second.currentRevision.value?.revision_id
    )
    expect(first.currentRevision.value).toMatchObject({
      persistence_state: 'draft',
      revision_number: null
    })
    expect(second.currentRevision.value).toMatchObject({
      persistence_state: 'draft',
      revision_number: null
    })
    expect(JSON.parse(JSON.stringify(first.currentRevision.value))).toEqual(
      first.currentRevision.value
    )
    expect(JSON.parse(JSON.stringify(second.currentRevision.value))).toEqual(
      second.currentRevision.value
    )
  })

  it('defines persisted revisions separately with positive server revision numbers', () => {
    const persisted = {
      revision_id: '55555555-5555-4555-8555-555555555555',
      document_id: documentId,
      verification_run_id: runId,
      source_version: sourceVersion,
      revision_number: 7,
      created_at: '2026-09-02T07:00:00.000Z',
      parent_revision_id: null,
      persistence_state: 'persisted',
      kind: 'review',
      text: '甲B丙丁'
    } satisfies PersistedDocumentRevision

    expect(persisted.persistence_state).toBe('persisted')
    expect(persisted.revision_number).toBeGreaterThan(0)
  })
})
