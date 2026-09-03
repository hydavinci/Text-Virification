import { reactive, toRaw } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useVerificationWorkspace } from '../src/composables/useVerificationWorkspace'
import type {
  PersistedDocumentRevision,
  TextBlock,
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

function buildBlock(overrides: Partial<TextBlock> = {}): TextBlock {
  return {
    block_id: 'p-0',
    kind: 'paragraph',
    text: '甲乙丙丁',
    global_start: 0,
    global_end: 4,
    block_start: 0,
    block_end: 4,
    page: null,
    paragraph_index: 0,
    table_index: null,
    row_index: null,
    cell_index: null,
    bbox: null,
    parent_id: null,
    style: {},
    source_locator: { paragraph_index: 0 },
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
      buildBlock({
        text,
        global_start: 0,
        global_end: codePointLength,
        block_start: 0,
        block_end: codePointLength
      })
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

function attemptAccessorReplacement<T extends object>(
  accessor: T,
  value: object | string | boolean | null
): void {
  const warning = vi.spyOn(console, 'warn').mockImplementation(() => {})
  try {
    Reflect.set(toRaw(accessor), 'value', value)
  } finally {
    warning.mockRestore()
  }
}

function expectSealedReactiveFacade<T>(
  facade: { readonly value: T },
  replacement: unknown
): T {
  const rawFacade = toRaw(facade)
  const originalValue = facade.value

  expect(rawFacade).toBe(facade)
  expect(Object.isFrozen(rawFacade)).toBe(true)
  expect(Reflect.ownKeys(rawFacade).sort()).toEqual(['__v_isRef', 'value'])
  expect(Object.prototype.hasOwnProperty.call(rawFacade, '_value')).toBe(false)
  expect(
    Object.getOwnPropertyDescriptor(rawFacade, 'value')?.set
  ).toBeUndefined()
  expect(() => {
    // @ts-expect-error Exercise runtime defense against hostile private access.
    rawFacade._value = replacement
  }).toThrow(TypeError)
  expect(Reflect.set(rawFacade, '_value', replacement)).toBe(false)
  expect(() => {
    // @ts-expect-error Exercise runtime defense beyond readonly type checking.
    rawFacade.value = replacement
  }).toThrow(TypeError)
  expect(Reflect.set(rawFacade, 'value', replacement)).toBe(false)
  expect(facade.value).toBe(originalValue)

  return originalValue
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

  it.each([
    ['forward', false],
    ['reversed', true]
  ])('fails closed for duplicate block ids in %s input order', (_label, reversed) => {
    const first = buildBlock({
      block_id: 'duplicate',
      text: '甲乙',
      global_start: 0,
      global_end: 2,
      block_end: 2
    })
    const second = buildBlock({
      block_id: 'duplicate',
      text: '丙丁',
      global_start: 2,
      global_end: 4,
      block_end: 2,
      paragraph_index: 1,
      source_locator: { paragraph_index: 1 }
    })
    const issue = buildIssue({
      block_id: 'duplicate',
      start: 2,
      end: 3,
      block_start: 0,
      block_end: 1,
      original: '丙'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue], {
      blocks: reversed ? [second, first] : [first, second]
    }))

    expect(workspace.visibleIssues.value).toEqual([])
  })

  it('accepts one empty block id using the backend canonical contract', () => {
    const issue = buildIssue({ block_id: '' })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue], {
      blocks: [buildBlock({ block_id: '' })]
    }))
    workspace.acceptIssue(issue.issue_id)

    expect(workspace.visibleIssues.value).toEqual([issue])
    expect(workspace.modifiedText.value).toBe('甲B丙丁')
  })

  it.each([
    ['forward', false],
    ['reversed', true]
  ])('fails closed for duplicate empty block ids in %s input order', (
    _label,
    reversed
  ) => {
    const first = buildBlock({
      block_id: '',
      text: '甲乙',
      global_start: 0,
      global_end: 2,
      block_end: 2
    })
    const second = buildBlock({
      block_id: '',
      text: '丙丁',
      global_start: 2,
      global_end: 4,
      block_end: 2,
      paragraph_index: 1,
      source_locator: { paragraph_index: 1 }
    })
    const issue = buildIssue({
      block_id: '',
      start: 2,
      end: 3,
      block_start: 0,
      block_end: 1,
      original: '丙'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue], {
      blocks: reversed ? [second, first] : [first, second]
    }))

    expect(workspace.visibleIssues.value).toEqual([])
  })

  it.each([
    ['non-string block ids', 'block_id'],
    ['non-string parent ids', 'parent_id']
  ] as const)('fails closed for %s', (_label, field) => {
    const block = buildBlock()
    Reflect.set(block, field, 7)
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([buildIssue()], { blocks: [block] }))

    expect(workspace.visibleIssues.value).toEqual([])
  })

  it.each([
    {
      label: 'a global range whose length differs from block text',
      blocks: [buildBlock({ text: '甲乙', global_end: 4, block_end: 2 })],
      issue: buildIssue()
    },
    {
      label: 'a nonzero local block start',
      blocks: [buildBlock({ block_start: 1, block_end: 5 })],
      issue: buildIssue({ block_start: 2, block_end: 3 })
    },
    {
      label: 'block text that differs from the document slice',
      blocks: [buildBlock({ text: '甲乙丙错' })],
      issue: buildIssue()
    },
    {
      label: 'a missing parent',
      blocks: [buildBlock({ parent_id: 'missing' })],
      issue: buildIssue()
    },
    {
      label: 'a self parent',
      blocks: [buildBlock({ parent_id: 'p-0' })],
      issue: buildIssue()
    },
    {
      label: 'a parent that does not contain its child',
      blocks: [
        buildBlock({ parent_id: 'parent' }),
        buildBlock({
          block_id: 'parent',
          text: '甲',
          global_end: 1,
          block_end: 1,
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ],
      issue: buildIssue()
    },
    {
      label: 'a parent cycle',
      blocks: [
        buildBlock({ parent_id: 'p-1' }),
        buildBlock({
          block_id: 'p-1',
          parent_id: 'p-0',
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ],
      issue: buildIssue()
    },
    {
      label: 'overlapping sibling ranges',
      blocks: [
        buildBlock({ text: '甲乙丙', global_end: 3, block_end: 3 }),
        buildBlock({
          block_id: 'p-1',
          text: '乙丙丁',
          global_start: 1,
          block_end: 3,
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ],
      issue: buildIssue()
    }
  ])('fails closed for $label', ({ blocks, issue }) => {
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue], { blocks }))

    expect(workspace.visibleIssues.value).toEqual([])
    expect(workspace.summary.value.total).toBe(0)
  })

  it('allows overlapping ancestor and descendant blocks with astral code-point ranges', () => {
    const text = '前😀乙后'
    const issue = buildIssue({
      block_id: 'child',
      start: 2,
      end: 3,
      block_start: 1,
      block_end: 2,
      original: '乙',
      suggestion: 'B'
    })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([issue], {
      text,
      blocks: [
        buildBlock({
          block_id: 'parent',
          text: '😀乙',
          global_start: 1,
          global_end: 3,
          block_end: 2
        }),
        buildBlock({
          block_id: 'child',
          text: '😀乙',
          global_start: 1,
          global_end: 3,
          block_end: 2,
          parent_id: 'parent',
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ]
    }))
    workspace.acceptIssue(issue.issue_id)

    expect(workspace.visibleIssues.value).toEqual([issue])
    expect(workspace.modifiedText.value).toBe('前😀B后')
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
    workspace.setIssueState(issueB.issue_id, 'pending')

    workspace.acceptIssues([issueA.issue_id, issueB.issue_id])
    expect(workspace.canUndoLastBatch.value).toBe(true)
    workspace.undoLastBatch()

    expect(Object.hasOwn(workspace.issueStates.value, issueA.issue_id)).toBe(false)
    expect(Object.hasOwn(workspace.issueStates.value, issueB.issue_id)).toBe(true)
    expect(workspace.issueStates.value[issueB.issue_id]).toBe('pending')
    expect(workspace.canUndoLastBatch.value).toBe(false)
  })

  it('undoes an overlapping batch exactly without publishing a partial revision', () => {
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

    expect(workspace.currentRevision.value).toBe(source)
    expect(workspace.hasReplacementConflicts.value).toBe(true)
    expect(workspace.canUndoLastBatch.value).toBe(true)

    workspace.undoLastBatch()

    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.hasReplacementConflicts.value).toBe(false)
    expect(workspace.currentRevision.value).toBe(source)
    expect(workspace.canUndoLastBatch.value).toBe(false)
  })

  it.each([
    ['new result', (workspace: ReturnType<typeof useVerificationWorkspace>) => {
      const nextRunId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
      workspace.loadResult(buildResult([
        buildIssue({ verification_run_id: nextRunId })
      ], {
        verification_run_id: nextRunId
      }))
    }],
    ['clear result', (workspace: ReturnType<typeof useVerificationWorkspace>) => {
      workspace.clearResult()
    }],
    ['manual edit', (workspace: ReturnType<typeof useVerificationWorkspace>) => {
      workspace.saveManualEdit('手工修改')
    }]
  ])('clears batch undo eligibility after %s', (_label, resetWorkspace) => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssues([issue.issue_id])
    expect(workspace.canUndoLastBatch.value).toBe(true)

    resetWorkspace(workspace)

    expect(workspace.canUndoLastBatch.value).toBe(false)
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

  it.each([
    ['undo', 'undoIssue'],
    ['reject', 'rejectIssue']
  ] as const)(
    'creates an authored source-text draft when %s returns accepted text to source',
    (_label, returnToSource) => {
      const issue = buildIssue()
      const workspace = useVerificationWorkspace()
      workspace.loadResult(buildResult([issue]))
      workspace.acceptIssue(issue.issue_id)
      const acceptedRevision = workspace.currentRevision.value

      workspace[returnToSource](issue.issue_id)

      expect(acceptedRevision).toMatchObject({
        kind: 'review',
        persistence_state: 'draft',
        text: '甲B丙丁'
      })
      expect(workspace.currentRevision.value).toMatchObject({
        kind: 'review',
        persistence_state: 'draft',
        revision_number: null,
        parent_revision_id: acceptedRevision?.revision_id,
        text: '甲乙丙丁'
      })
      expect(workspace.currentRevision.value?.revision_id).toMatch(uuidPattern)
      expect(workspace.currentRevision.value?.revision_id).not.toBe(
        acceptedRevision?.revision_id
      )
    }
  )

  it('clones loaded results so caller mutation cannot retarget accepted replacements', () => {
    const issue = buildIssue()
    const input = buildResult([issue])
    const workspace = useVerificationWorkspace()
    workspace.loadResult(input)

    input.text = '篡改文本'
    input.blocks[0].text = '篡改文本'
    input.blocks[0].global_start = 2
    issue.start = 0
    issue.end = 1
    issue.block_start = 0
    issue.block_end = 1
    issue.original = '甲'
    issue.suggestion = '篡改替换'
    input.issues.push(buildIssue({
      issue_id: '55555555-5555-4555-8555-555555555555'
    }))

    workspace.acceptIssue(issue.issue_id)

    expect(workspace.result.value?.text).toBe('甲乙丙丁')
    expect(workspace.result.value?.blocks[0]).toMatchObject({
      text: '甲乙丙丁',
      global_start: 0
    })
    expect(workspace.visibleIssues.value).toHaveLength(1)
    expect(workspace.visibleIssues.value[0]).toMatchObject({
      start: 1,
      end: 2,
      original: '乙',
      suggestion: 'B'
    })
    expect(workspace.modifiedText.value).toBe('甲B丙丁')
  })

  it('clones Vue reactive result proxies before freezing canonical state', () => {
    const issue = buildIssue()
    const input = buildResult([issue])
    const reactiveInput = reactive(input)
    const workspace = useVerificationWorkspace()

    expect(() => workspace.loadResult(reactiveInput)).not.toThrow()
    input.text = '篡改文本'
    issue.suggestion = '篡改替换'
    workspace.acceptIssue(issue.issue_id)

    expect(workspace.result.value?.text).toBe('甲乙丙丁')
    expect(workspace.modifiedText.value).toBe('甲B丙丁')
  })

  it('recursively freezes loaded results and canonical issue arrays', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    const loaded = workspace.result.value
    if (loaded === null) {
      throw new Error('Expected a loaded result')
    }
    const visible = workspace.visibleIssues.value

    expect(Object.isFrozen(loaded)).toBe(true)
    expect(Object.isFrozen(loaded.blocks)).toBe(true)
    expect(Object.isFrozen(loaded.blocks[0])).toBe(true)
    expect(Object.isFrozen(loaded.blocks[0].source_locator)).toBe(true)
    expect(Object.isFrozen(loaded.issues)).toBe(true)
    expect(Object.isFrozen(loaded.issues[0])).toBe(true)
    expect(Object.isFrozen(loaded.issues[0].alternatives)).toBe(true)
    expect(Object.isFrozen(visible)).toBe(true)
    expect(Reflect.set(loaded, 'text', '篡改文本')).toBe(false)
    expect(Reflect.set(visible[0], 'suggestion', '篡改替换')).toBe(false)
    expect(() =>
      Reflect.apply(Array.prototype.push, loaded.issues, [buildIssue()])
    ).toThrow(TypeError)
    expect(() =>
      Reflect.apply(Array.prototype.push, visible, [buildIssue()])
    ).toThrow(TypeError)
    expect(loaded.text).toBe('甲乙丙丁')
    expect(visible).toEqual([issue])
  })

  it('exposes every reactive value through a frozen facade without Vue internals', () => {
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
    workspace.loadResult(buildResult([earlier, later], { text: 'abcdef' }))
    workspace.selectSuggestion(earlier.issue_id, 'SAFE')
    workspace.acceptIssues([earlier.issue_id, later.issue_id])

    expectSealedReactiveFacade(workspace.result, buildResult([]))
    expectSealedReactiveFacade(workspace.issueStates, {
      [earlier.issue_id]: 'rejected'
    })
    expectSealedReactiveFacade(workspace.selectedSuggestions, {
      [earlier.issue_id]: 'POISON'
    })
    expectSealedReactiveFacade(workspace.currentRevision, null)
    expectSealedReactiveFacade(workspace.requiresReverification, true)
    expectSealedReactiveFacade(workspace.modifiedText, 'POISON')
    expectSealedReactiveFacade(workspace.visibleIssues, [])
    expectSealedReactiveFacade(workspace.summary, {
      total: 0,
      pending: 0,
      accepted: 0,
      rejected: 0
    })
    expectSealedReactiveFacade(workspace.replacementConflictIssueIds, [])
    expectSealedReactiveFacade(workspace.hasReplacementConflicts, false)

    expect(workspace.result.value?.text).toBe('abcdef')
    expect(workspace.issueStates.value).toEqual({
      [earlier.issue_id]: 'accepted',
      [later.issue_id]: 'accepted'
    })
    expect(workspace.selectedSuggestions.value).toEqual({
      [earlier.issue_id]: 'SAFE'
    })
    expect(workspace.currentRevision.value?.kind).toBe('source')
    expect(workspace.requiresReverification.value).toBe(false)
    expect(workspace.modifiedText.value).toBe('abcdef')
    expect(workspace.visibleIssues.value).toEqual([earlier, later])
    expect(workspace.summary.value).toEqual({
      total: 2,
      pending: 0,
      accepted: 2,
      rejected: 0
    })
    expect(workspace.replacementConflictIssueIds.value).toEqual([
      earlier.issue_id,
      later.issue_id
    ])
    expect(workspace.hasReplacementConflicts.value).toBe(true)
  })

  it('keeps facade reads reactive while preserving frozen container values', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    const facades = {
      result: workspace.result,
      issueStates: workspace.issueStates,
      selectedSuggestions: workspace.selectedSuggestions,
      currentRevision: workspace.currentRevision,
      requiresReverification: workspace.requiresReverification,
      modifiedText: workspace.modifiedText,
      visibleIssues: workspace.visibleIssues,
      summary: workspace.summary,
      replacementConflictIssueIds: workspace.replacementConflictIssueIds,
      hasReplacementConflicts: workspace.hasReplacementConflicts
    }

    workspace.loadResult(buildResult([issue]))
    workspace.selectSuggestion(issue.issue_id, '用户选择')
    workspace.acceptIssue(issue.issue_id)

    expect(workspace.result).toBe(facades.result)
    expect(workspace.issueStates).toBe(facades.issueStates)
    expect(workspace.selectedSuggestions).toBe(facades.selectedSuggestions)
    expect(workspace.currentRevision).toBe(facades.currentRevision)
    expect(workspace.requiresReverification).toBe(
      facades.requiresReverification
    )
    expect(workspace.modifiedText).toBe(facades.modifiedText)
    expect(workspace.visibleIssues).toBe(facades.visibleIssues)
    expect(workspace.summary).toBe(facades.summary)
    expect(workspace.replacementConflictIssueIds).toBe(
      facades.replacementConflictIssueIds
    )
    expect(workspace.hasReplacementConflicts).toBe(
      facades.hasReplacementConflicts
    )
    expect(workspace.result.value?.text).toBe('甲乙丙丁')
    expect(workspace.issueStates.value).toEqual({
      [issue.issue_id]: 'accepted'
    })
    expect(workspace.selectedSuggestions.value).toEqual({
      [issue.issue_id]: '用户选择'
    })
    expect(workspace.currentRevision.value?.text).toBe('甲用户选择丙丁')
    expect(workspace.requiresReverification.value).toBe(false)
    expect(workspace.modifiedText.value).toBe('甲用户选择丙丁')
    expect(workspace.visibleIssues.value).toEqual([issue])
    expect(workspace.summary.value).toEqual({
      total: 1,
      pending: 0,
      accepted: 1,
      rejected: 0
    })
    expect(workspace.replacementConflictIssueIds.value).toEqual([])
    expect(workspace.hasReplacementConflicts.value).toBe(false)

    expect(Object.isFrozen(workspace.result.value)).toBe(true)
    expect(Object.isFrozen(workspace.issueStates.value)).toBe(true)
    expect(Object.isFrozen(workspace.selectedSuggestions.value)).toBe(true)
    expect(Object.isFrozen(workspace.currentRevision.value)).toBe(true)
    expect(Object.isFrozen(workspace.visibleIssues.value)).toBe(true)
    expect(Object.isFrozen(workspace.summary.value)).toBe(true)
    expect(Object.isFrozen(workspace.replacementConflictIssueIds.value)).toBe(
      true
    )

    workspace.saveManualEdit('手工修改')

    expect(workspace.result.value?.text).toBe('甲乙丙丁')
    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.selectedSuggestions.value).toEqual({})
    expect(workspace.currentRevision.value?.text).toBe('手工修改')
    expect(workspace.requiresReverification.value).toBe(true)
    expect(workspace.modifiedText.value).toBe('手工修改')
    expect(workspace.visibleIssues.value).toEqual([])
    expect(workspace.summary.value).toEqual({
      total: 0,
      pending: 0,
      accepted: 0,
      rejected: 0
    })
    expect(workspace.replacementConflictIssueIds.value).toEqual([])
    expect(workspace.hasReplacementConflicts.value).toBe(false)
  })

  it('returns frozen public snapshots and computed containers', () => {
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
    workspace.selectSuggestion(earlier.issue_id, 'SAFE')
    workspace.acceptIssues([earlier.issue_id, later.issue_id])

    const loaded = workspace.result.value
    const revision = workspace.currentRevision.value
    const decisions = workspace.issueStates.value
    const suggestions = workspace.selectedSuggestions.value
    const reviewSummary = workspace.summary.value
    const conflictIds = workspace.replacementConflictIssueIds.value
    const visible = workspace.visibleIssues.value
    const canUndo = workspace.canUndoLastBatch.value

    attemptAccessorReplacement(workspace.summary, {
      total: 0,
      pending: 0,
      accepted: 0,
      rejected: 0
    })
    attemptAccessorReplacement(workspace.replacementConflictIssueIds, [])
    attemptAccessorReplacement(workspace.visibleIssues, [])
    attemptAccessorReplacement(workspace.canUndoLastBatch, false)

    expect(workspace.summary.value).toBe(reviewSummary)
    expect(workspace.replacementConflictIssueIds.value).toBe(conflictIds)
    expect(workspace.visibleIssues.value).toBe(visible)
    expect(workspace.canUndoLastBatch.value).toBe(canUndo)
    expectSealedReactiveFacade(workspace.canUndoLastBatch, false)
    expect(Object.isFrozen(loaded)).toBe(true)
    expect(Object.isFrozen(revision)).toBe(true)
    expect(Object.isFrozen(decisions)).toBe(true)
    expect(Object.isFrozen(suggestions)).toBe(true)
    expect(Object.isFrozen(reviewSummary)).toBe(true)
    expect(Object.isFrozen(conflictIds)).toBe(true)
    expect(Object.isFrozen(visible)).toBe(true)
    expect(Object.isFrozen(visible[0])).toBe(true)

    if (loaded === null || revision === null) {
      throw new Error('Expected loaded immutable workspace values')
    }
    expect(Reflect.set(loaded, 'text', '篡改文本')).toBe(false)
    expect(Reflect.set(revision, 'text', '篡改修订')).toBe(false)
    expect(Reflect.set(decisions, earlier.issue_id, 'rejected')).toBe(false)
    expect(Reflect.set(suggestions, earlier.issue_id, '篡改替换')).toBe(false)
    expect(Reflect.set(reviewSummary, 'accepted', 0)).toBe(false)
    expect(Reflect.set(visible[0], 'suggestion', '篡改替换')).toBe(false)
    expect(() =>
      Reflect.apply(Array.prototype.push, conflictIds, [earlier.issue_id])
    ).toThrow(TypeError)
    expect(() =>
      Reflect.apply(Array.prototype.push, visible, [buildIssue()])
    ).toThrow(TypeError)

    expect(workspace.result.value?.text).toBe('abcdef')
    expect(workspace.currentRevision.value).toBe(revision)
    expect(workspace.issueStates.value).toEqual({
      [earlier.issue_id]: 'accepted',
      [later.issue_id]: 'accepted'
    })
    expect(workspace.selectedSuggestions.value).toEqual({
      [earlier.issue_id]: 'SAFE'
    })
    expect(workspace.summary.value).toEqual({
      total: 2,
      pending: 0,
      accepted: 2,
      rejected: 0
    })
    expect(workspace.replacementConflictIssueIds.value).toEqual([
      earlier.issue_id,
      later.issue_id
    ])
    expect(workspace.visibleIssues.value).toEqual([earlier, later])
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

  it('clears canonical result and stable-id review state for a workspace reset', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)
    workspace.selectSuggestion(issue.issue_id, '替代')

    workspace.clearResult()

    expect(workspace.result.value).toBeNull()
    expect(workspace.visibleIssues.value).toEqual([])
    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.selectedSuggestions.value).toEqual({})
    expect(workspace.currentRevision.value).toBeNull()
    expect(workspace.summary.value).toEqual({
      total: 0,
      pending: 0,
      accepted: 0,
      rejected: 0
    })

    workspace.loadResult(buildResult([issue]))
    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.selectedSuggestions.value).toEqual({})
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
