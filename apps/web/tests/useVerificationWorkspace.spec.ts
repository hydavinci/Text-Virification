import { reactive, toRaw } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import {
  createVerificationResultSnapshot,
  hasCanonicalBlocks,
  useVerificationWorkspace
} from '../src/composables/useVerificationWorkspace'
import type {
  PdfDocumentMetadata,
  PersistedDocumentRevision,
  TextBlock,
  VerificationIssue,
  VerificationResult
} from '../src/types/verification'

const documentId = '11111111-1111-1111-8111-111111111111'
const runId = '22222222-2222-2222-8222-222222222222'
const sourceVersion = 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const MAX_VERIFICATION_ISSUES = 100_000
const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function buildIssue(overrides: Partial<VerificationIssue> = {}): VerificationIssue {
  const issue: VerificationIssue = {
    issue_id: '33333333-3333-3333-8333-333333333333',
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
    position: 1,
    end_position: 2,
    review: null,
    review_reason: null,
    ...overrides
  }
  if (!Object.prototype.hasOwnProperty.call(overrides, 'position')) {
    issue.position = issue.start
  }
  if (!Object.prototype.hasOwnProperty.call(overrides, 'end_position')) {
    issue.end_position = issue.end
  }
  return issue
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
  const countBy = (keyFor: (issue: VerificationIssue) => string) =>
    issues.reduce<Record<string, number>>((counts, issue) => {
      const key = keyFor(issue)
      counts[key] = (counts[key] ?? 0) + 1
      return counts
    }, {})
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
      by_type: countBy((issue) => issue.type),
      by_severity: countBy((issue) => issue.severity),
      by_rule: countBy((issue) => issue.rule_id),
      by_layer: countBy((issue) => issue.layer)
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

function sourceRevisionFor(result: VerificationResult) {
  return {
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
  }
}

function buildSessionV2(
  result: VerificationResult,
  overrides: Record<string, unknown> = {}
) {
  return {
    version: 2,
    result,
    currentRevision: sourceRevisionFor(result),
    requiresReverification: false,
    issueStates: {},
    selectedSuggestions: {},
    ...overrides
  }
}

function issueIdForIndex(index: number): string {
  return `40000000-0000-4000-8000-${index.toString().padStart(12, '0')}`
}

function buildLargeReplacementScenario(issueCount = MAX_VERIFICATION_ISSUES) {
  const text = 'a'.repeat(issueCount)
  const issues = Array.from({ length: issueCount }, (_, index) =>
    buildIssue({
      issue_id: issueIdForIndex(index),
      start: index,
      end: index + 1,
      block_start: index,
      block_end: index + 1,
      original: 'a',
      suggestion: 'b',
      context: text,
      position: index,
      end_position: index + 1
    })
  )
  return {
    text,
    issues,
    issueIds: issues.map((issue) => issue.issue_id),
    expectedText: 'b'.repeat(issueCount)
  }
}

function mutableSnapshotFor(result: VerificationResult): VerificationResult {
  const freeze = vi.spyOn(Object, 'freeze').mockImplementation(
    <T>(value: T): Readonly<T> => value
  )
  try {
    const snapshot = createVerificationResultSnapshot(result)
    expect(snapshot).not.toBeNull()
    return snapshot!
  } finally {
    freeze.mockRestore()
  }
}

function countIssueRangeReads(
  issues: readonly VerificationIssue[],
  budget: number
) {
  let rangeReads = 0
  for (const issue of issues) {
    for (const key of ['start', 'end'] as const) {
      const value = issue[key]
      Object.defineProperty(issue, key, {
        configurable: true,
        enumerable: true,
        get() {
          rangeReads += 1
          if (rangeReads > budget) {
            throw new Error(`accepted replacement range read budget exceeded: ${rangeReads}`)
          }
          return value
        }
      })
    }
  }
  return () => rangeReads
}

function buildPdfMetadata(): PdfDocumentMetadata {
  return {
    pages: [
      {
        page: 1,
        kind: 'scanned',
        page_bbox: [0, 0, 100, 200],
        text_length: 2,
        text_density: 0.0001,
        image_coverage: 0.5,
        ocr_required: true,
        spans: [
          {
            text: 'W',
            bbox: [1, 2, 9, 12],
            font_name: 'Helvetica',
            font_size: 10,
            font_flags: 0,
            color: 0,
            span_index: 0,
            characters: [
              {
                text: 'W',
                bbox: [1, 2, 9, 12],
                source_start: 0,
                source_end: 1,
                mapping_state: 'glyph',
                group_id: 'span-glyph-0',
                line_direction: [1, 0],
                writing_mode: 0,
                raw_line_index: 0,
                span_order: 0
              }
            ],
            line_direction: [1, 0],
            writing_mode: 0,
            line_index: 0,
            span_order: 0
          }
        ],
        tables: [
          {
            table_index: 0,
            bbox: [10, 20, 90, 80],
            row_count: 1,
            column_count: 1,
            rows: [
              [
                {
                  text: 'T',
                  bbox: [11, 21, 20, 30],
                  table_index: 0,
                  row_index: 0,
                  cell_index: 0,
                  characters: [
                    {
                      text: 'T',
                      bbox: [11, 21, 20, 30],
                      source_start: 0,
                      source_end: 1,
                      mapping_state: 'glyph',
                      group_id: 'cell-glyph-0',
                      line_direction: [1, 0],
                      writing_mode: 0,
                      raw_line_index: 0,
                      span_order: null
                    }
                  ]
                }
              ]
            ]
          }
        ],
        images: [
          {
            image_index: 0,
            xref: 1,
            bbox: [20, 90, 80, 190]
          }
        ]
      }
    ],
    warnings: [
      {
        page: 1,
        stage: 'ocr',
        code: 'pdf_ocr_no_text',
        message: 'OCR required'
      }
    ],
    ocr_requirement: {
      mode: 'required',
      pages: [1]
    }
  }
}

function buildPdfResult(): VerificationResult {
  const ocrRequirement = {
    mode: 'required' as const,
    pages: [1]
  }
  return buildResult([buildIssue({ page: 1 })], {
    filename: 'sample.pdf',
    source_name: 'sample.pdf',
    file_type: 'pdf',
    file_ext: '.pdf',
    pdf_metadata: buildPdfMetadata(),
    ocr_requirement: ocrRequirement
  })
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
      issue_id: '44444444-4444-4444-8444-444444444444',
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
      issue_id: '44444444-4444-4444-8444-444444444444',
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
        document_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        issues: [
          buildIssue({
            document_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
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
      issue_id: '44444444-4444-4444-8444-444444444444',
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

  it('plans live accepted replacement work structurally for 100000 accepted replacements', () => {
    const scenario = buildLargeReplacementScenario()
    const snapshot = mutableSnapshotFor(
      buildResult(scenario.issues, { text: scenario.text })
    )
    const rangeReads = countIssueRangeReads(snapshot.issues, 10_000_000)
    const workspace = useVerificationWorkspace()

    workspace.loadResult(snapshot)
    expect(() => workspace.acceptIssues(scenario.issueIds)).not.toThrow()

    expect(workspace.hasReplacementConflicts.value).toBe(false)
    expect(workspace.modifiedText.value).toBe(scenario.expectedText)
    expect(rangeReads()).toBeLessThan(10_000_000)
  })

  it('plans restored accepted replacement work structurally for 100000 accepted replacements', () => {
    const scenario = buildLargeReplacementScenario()
    const snapshot = mutableSnapshotFor(
      buildResult(scenario.issues, { text: scenario.text })
    )
    const rangeReads = countIssueRangeReads(snapshot.issues, 10_000_000)
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(buildSessionV2(snapshot, {
      issueStates: Object.fromEntries(
        scenario.issueIds.map((issueId) => [issueId, 'accepted'])
      ),
      currentRevision: {
        revision_id: '55555555-5555-4555-8555-555555555555',
        document_id: documentId,
        verification_run_id: runId,
        source_version: sourceVersion,
        revision_number: null,
        created_at: '2026-09-03T02:00:00.000Z',
        parent_revision_id: null,
        persistence_state: 'draft',
        kind: 'review',
        text: scenario.expectedText
      }
    }))).toBe(true)

    expect(workspace.hasReplacementConflicts.value).toBe(false)
    expect(workspace.modifiedText.value).toBe(scenario.expectedText)
    expect(rangeReads()).toBeLessThan(10_000_000)
  })

  it('avoids repeated code-point rescans for accepted replacements in a 100000-code-point source', () => {
    const scenario = buildLargeReplacementScenario()
    const snapshot = mutableSnapshotFor(
      buildResult(scenario.issues, { text: scenario.text })
    )
    const workspace = useVerificationWorkspace()
    workspace.loadResult(snapshot)
    let codePointIterations = 0
    const budget = 250_000
    const originalIterator = String.prototype[Symbol.iterator]
    const iterator = vi.spyOn(String.prototype, Symbol.iterator).mockImplementation(
      function (this: string): IterableIterator<string> {
        const source = originalIterator.call(this)
        return {
          next(): IteratorResult<string> {
            const next = source.next()
            if (!next.done) {
              codePointIterations += 1
              if (codePointIterations > budget) {
                throw new Error(`code-point iteration budget exceeded: ${codePointIterations}`)
              }
            }
            return next
          },
          [Symbol.iterator](): IterableIterator<string> {
            return this
          }
        }
      }
    )

    try {
      const acceptedIds = scenario.issueIds.slice(-3)
      expect(() => workspace.acceptIssues(acceptedIds)).not.toThrow()
      expect(workspace.modifiedText.value.endsWith('bbb')).toBe(true)
      expect(codePointIterations).toBeLessThan(budget)
    } finally {
      iterator.mockRestore()
    }
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

  it('fails closed when one sibling block range contains another', () => {
    const workspace = useVerificationWorkspace()

    workspace.loadResult(
      buildResult([buildIssue()], {
        blocks: [
          buildBlock(),
          buildBlock({
            block_id: 'p-1',
            text: '乙丙',
            global_start: 1,
            global_end: 3,
            block_end: 2,
            paragraph_index: 1,
            source_locator: { paragraph_index: 1 }
          })
        ]
      })
    )

    expect(workspace.result.value).toBeNull()
    expect(workspace.visibleIssues.value).toEqual([])
  })

  it.each([
    {
      label: 'a root point strictly inside a non-ancestor root',
      expected: false,
      blocks: [
        buildBlock({ block_id: 'interval' }),
        buildBlock({
          block_id: 'point',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ]
    },
    {
      label: 'a sibling point strictly inside a sibling interval',
      expected: false,
      blocks: [
        buildBlock({ block_id: 'root' }),
        buildBlock({
          block_id: 'interval',
          text: '甲乙丙',
          global_end: 3,
          block_end: 3,
          parent_id: 'root',
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        }),
        buildBlock({
          block_id: 'point',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          parent_id: 'root',
          paragraph_index: 2,
          source_locator: { paragraph_index: 2 }
        })
      ]
    },
    {
      label: 'an unrelated point at a nested child start but inside its outer ancestor',
      expected: false,
      blocks: [
        buildBlock({ block_id: 'outer' }),
        buildBlock({
          block_id: 'child',
          text: '丙',
          global_start: 2,
          global_end: 3,
          block_end: 1,
          parent_id: 'outer',
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        }),
        buildBlock({
          block_id: 'point',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          paragraph_index: 2,
          source_locator: { paragraph_index: 2 }
        })
      ]
    },
    {
      label: 'an unrelated point at a nested child end but inside its outer ancestor',
      expected: false,
      blocks: [
        buildBlock({ block_id: 'outer' }),
        buildBlock({
          block_id: 'child',
          text: '乙',
          global_start: 1,
          global_end: 2,
          block_end: 1,
          parent_id: 'outer',
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        }),
        buildBlock({
          block_id: 'point',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          paragraph_index: 2,
          source_locator: { paragraph_index: 2 }
        })
      ]
    },
    {
      label: 'a point strictly inside its ancestor',
      expected: true,
      blocks: [
        buildBlock({ block_id: 'ancestor' }),
        buildBlock({
          block_id: 'point',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          parent_id: 'ancestor',
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ]
    },
    {
      label: 'a non-ancestor point at the interval start',
      expected: true,
      blocks: [
        buildBlock({ block_id: 'interval' }),
        buildBlock({
          block_id: 'point',
          text: '',
          global_end: 0,
          block_end: 0,
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ]
    },
    {
      label: 'a non-ancestor point at the interval end',
      expected: true,
      blocks: [
        buildBlock({ block_id: 'interval' }),
        buildBlock({
          block_id: 'point',
          text: '',
          global_start: 4,
          global_end: 4,
          block_end: 0,
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ]
    },
    {
      label: 'equal sibling points',
      expected: true,
      blocks: [
        buildBlock({
          block_id: 'first',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0
        }),
        buildBlock({
          block_id: 'second',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ]
    },
    {
      label: 'equal cousin points',
      expected: true,
      blocks: [
        buildBlock({
          block_id: 'first-parent',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0
        }),
        buildBlock({
          block_id: 'second-parent',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        }),
        buildBlock({
          block_id: 'first-point',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          parent_id: 'first-parent',
          paragraph_index: 2,
          source_locator: { paragraph_index: 2 }
        }),
        buildBlock({
          block_id: 'second-point',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          parent_id: 'second-parent',
          paragraph_index: 3,
          source_locator: { paragraph_index: 3 }
        })
      ]
    },
    {
      label: 'equal ancestor and descendant points',
      expected: true,
      blocks: [
        buildBlock({
          block_id: 'point-parent',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0
        }),
        buildBlock({
          block_id: 'point-child',
          text: '',
          global_start: 2,
          global_end: 2,
          block_end: 0,
          parent_id: 'point-parent',
          paragraph_index: 1,
          source_locator: { paragraph_index: 1 }
        })
      ]
    }
  ])('matches backend zero-length overlap semantics for $label in unsorted input', ({
    expected,
    blocks
  }) => {
    expect(
      hasCanonicalBlocks(
        buildResult([], {
          blocks: [blocks.at(-1)!, ...blocks.slice(0, -1).reverse()]
        })
      )
    ).toBe(expected)
  })

  it('checks large disjoint block sets without quadratic range comparisons', () => {
    const blockCount = 2_000
    let rangeReads = 0
    const text = 'x'.repeat(blockCount)
    const blocks = Array.from({ length: blockCount }, (_, index) => {
      const block = buildBlock({
        block_id: `p-${index}`,
        text: 'x',
        global_start: index,
        global_end: index + 1,
        block_end: 1,
        paragraph_index: index,
        source_locator: { paragraph_index: index }
      })
      for (const key of ['global_start', 'global_end'] as const) {
        const value = block[key]
        Object.defineProperty(block, key, {
          configurable: true,
          enumerable: true,
          get() {
            rangeReads += 1
            return value
          }
        })
      }
      return block
    })

    expect(hasCanonicalBlocks(buildResult([], { text, blocks }))).toBe(true)
    expect(rangeReads).toBeLessThan(blockCount * 50)
  })

  it('checks many equal-start point boundaries without scanning the active ancestry chain', () => {
    const intervalCount = 1_000
    const text = 'x'.repeat(intervalCount)
    let rangeReads = 0
    const intervals = Array.from({ length: intervalCount }, (_, index) => {
      const end = intervalCount - index
      const block = buildBlock({
        block_id: `interval-${index}`,
        text: text.slice(0, end),
        global_start: 0,
        global_end: end,
        block_end: end,
        parent_id: index === 0 ? null : `interval-${index - 1}`,
        paragraph_index: index,
        source_locator: { paragraph_index: index }
      })
      for (const key of ['global_start', 'global_end'] as const) {
        const value = block[key]
        Object.defineProperty(block, key, {
          configurable: true,
          enumerable: true,
          get() {
            rangeReads += 1
            return value
          }
        })
      }
      return block
    })
    const points = Array.from({ length: intervalCount }, (_, index) => {
      const block = buildBlock({
        block_id: `point-${index}`,
        text: '',
        global_start: 0,
        global_end: 0,
        block_end: 0,
        paragraph_index: intervalCount + index,
        source_locator: { paragraph_index: intervalCount + index }
      })
      for (const key of ['global_start', 'global_end'] as const) {
        const value = block[key]
        Object.defineProperty(block, key, {
          configurable: true,
          enumerable: true,
          get() {
            rangeReads += 1
            return value
          }
        })
      }
      return block
    })

    expect(
      hasCanonicalBlocks(
        buildResult([], { text, blocks: [...points.reverse(), ...intervals.reverse()] })
      )
    ).toBe(true)
    expect(rangeReads).toBeLessThan((intervalCount + points.length) * 50)
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

  it('uses canonical start and end while ignoring stale compatibility aliases', () => {
    const valid = buildIssue({ position: -50, end_position: -25 })
    const workspace = useVerificationWorkspace()

    workspace.loadResult(buildResult([valid]))
    workspace.acceptIssue(valid.issue_id)

    expect(workspace.visibleIssues.value.map((issue) => issue.issue_id)).toEqual([valid.issue_id])
    expect(workspace.issueStates.value).toEqual({ [valid.issue_id]: 'accepted' })
    expect(workspace.modifiedText.value).toBe('甲B丙丁')
  })

  it.each([
    ['forward', false],
    ['reversed', true]
  ])('preserves and counts overlapping issues in %s input order', (_label, reversed) => {
    const earlier = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000001',
      start: 1,
      end: 4,
      block_start: 1,
      block_end: 4,
      original: 'bcd',
      suggestion: 'X',
      context: 'abcdef'
    })
    const later = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000002',
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
        issue_id: '40000000-0000-4000-8000-000000000001',
        start: 1,
        end: 4,
        block_start: 1,
        block_end: 4,
        original: 'bcd',
        suggestion: 'X',
        context: 'abcdef'
      })
      const later = buildIssue({
        issue_id: '40000000-0000-4000-8000-000000000002',
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
      issue_id: '40000000-0000-4000-8000-000000000001',
      start: 1,
      end: 4,
      block_start: 1,
      block_end: 4,
      original: 'bcd',
      suggestion: 'X',
      context: 'abcdef'
    })
    const later = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000002',
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
      issue_id: '40000000-0000-4000-8000-000000000001',
      start: 1,
      end: 4,
      block_start: 1,
      block_end: 4,
      original: 'bcd',
      suggestion: 'X',
      context: 'abcdef'
    })
    const later = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000002',
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
      issue_id: '44444444-4444-4444-8444-444444444444',
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

  it('treats reset-all as the latest atomic batch and retains older batch history', () => {
    const issueA = buildIssue()
    const issueB = buildIssue({
      issue_id: '44444444-4444-4444-8444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: '丙',
      suggestion: 'C'
    })
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issueA, issueB]))

    workspace.setIssueStates(
      [issueA.issue_id, issueB.issue_id],
      'accepted'
    )
    workspace.setIssueStates(
      [issueA.issue_id, issueB.issue_id],
      'pending'
    )

    expect(workspace.issueStates.value).toEqual({
      [issueA.issue_id]: 'pending',
      [issueB.issue_id]: 'pending'
    })

    workspace.undoLastBatch()

    expect(workspace.issueStates.value).toEqual({
      [issueA.issue_id]: 'accepted',
      [issueB.issue_id]: 'accepted'
    })
    expect(workspace.canUndoLastBatch.value).toBe(true)

    workspace.undoLastBatch()

    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.canUndoLastBatch.value).toBe(false)
  })

  it('undoes an overlapping batch exactly without publishing a partial revision', () => {
    const earlier = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000001',
      start: 1,
      end: 4,
      block_start: 1,
      block_end: 4,
      original: 'bcd',
      suggestion: 'X',
      context: 'abcdef'
    })
    const later = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000002',
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

  it('restores decisions and explicit overrides atomically into one revision', () => {
    const issueA = buildIssue({
      start: 0,
      end: 1,
      block_start: 0,
      block_end: 1,
      original: 'a',
      suggestion: 'A',
      context: 'abcd'
    })
    const issueB = buildIssue({
      issue_id: '44444444-4444-4444-8444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: 'c',
      suggestion: 'C',
      context: 'abcd'
    })
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issueA, issueB], { text: 'abcd' }))

    workspace.restoreReviewState({
      documentId,
      verificationRunId: runId,
      sourceVersion,
      issueStates: {
        [issueA.issue_id]: 'accepted',
        [issueB.issue_id]: 'accepted'
      },
      selectedSuggestions: {
        [issueA.issue_id]: '',
        [issueB.issue_id]: 'SEE'
      }
    })

    expect(workspace.issueStates.value).toEqual({
      [issueA.issue_id]: 'accepted',
      [issueB.issue_id]: 'accepted'
    })
    expect(workspace.selectedSuggestions.value).toEqual({
      [issueA.issue_id]: '',
      [issueB.issue_id]: 'SEE'
    })
    expect(workspace.currentRevision.value).toMatchObject({
      kind: 'review',
      parent_revision_id: null,
      text: 'bSEEd'
    })
    expect(workspace.modifiedText.value).toBe('bSEEd')
    expect(workspace.canUndoLastBatch.value).toBe(false)
  })

  it('prunes stale and malformed restored values while preserving explicit null and empty overrides', () => {
    const issueA = buildIssue({
      start: 0,
      end: 1,
      block_start: 0,
      block_end: 1,
      original: 'a',
      suggestion: 'A',
      context: 'abcd'
    })
    const issueB = buildIssue({
      issue_id: '44444444-4444-4444-8444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: 'c',
      suggestion: 'C',
      context: 'abcd'
    })
    const staleId = '55555555-5555-4555-8555-555555555555'
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issueA, issueB], { text: 'abcd' }))
    workspace.setIssueStates([issueA.issue_id, issueB.issue_id], 'rejected')
    expect(workspace.canUndoLastBatch.value).toBe(true)

    workspace.restoreReviewState({
      documentId,
      verificationRunId: runId,
      sourceVersion,
      issueStates: {
        [issueA.issue_id]: 'accepted',
        [issueB.issue_id]: 'malformed',
        [staleId]: 'rejected'
      },
      selectedSuggestions: {
        [issueA.issue_id]: null,
        [issueB.issue_id]: '',
        [staleId]: 'stale',
        malformed: 42
      }
    })

    expect(workspace.issueStates.value).toEqual({
      [issueA.issue_id]: 'accepted'
    })
    expect(workspace.selectedSuggestions.value).toEqual({
      [issueA.issue_id]: null,
      [issueB.issue_id]: ''
    })
    expect(workspace.modifiedText.value).toBe('abcd')
    expect(workspace.canUndoLastBatch.value).toBe(false)
  })

  it('keeps the prior revision when restored accepted replacements conflict', () => {
    const priorIssue = buildIssue({
      start: 0,
      end: 1,
      block_start: 0,
      block_end: 1,
      original: 'a',
      suggestion: 'A',
      context: 'abcdefg'
    })
    const crossingA = buildIssue({
      issue_id: '44444444-4444-4444-8444-444444444444',
      start: 2,
      end: 5,
      block_start: 2,
      block_end: 5,
      original: 'cde',
      suggestion: 'X',
      context: 'abcdefg'
    })
    const crossingB = buildIssue({
      issue_id: '55555555-5555-4555-8555-555555555555',
      start: 4,
      end: 7,
      block_start: 4,
      block_end: 7,
      original: 'efg',
      suggestion: 'Y',
      context: 'abcdefg'
    })
    const workspace = useVerificationWorkspace()
    workspace.loadResult(
      buildResult([priorIssue, crossingA, crossingB], { text: 'abcdefg' })
    )
    workspace.acceptIssue(priorIssue.issue_id)
    const priorRevision = workspace.currentRevision.value

    workspace.restoreReviewState({
      documentId,
      verificationRunId: runId,
      sourceVersion,
      issueStates: {
        [crossingA.issue_id]: 'accepted',
        [crossingB.issue_id]: 'accepted'
      },
      selectedSuggestions: {}
    })

    expect(workspace.issueStates.value).toEqual({
      [crossingA.issue_id]: 'accepted',
      [crossingB.issue_id]: 'accepted'
    })
    expect(workspace.hasReplacementConflicts.value).toBe(true)
    expect(workspace.currentRevision.value).toBe(priorRevision)
    expect(workspace.modifiedText.value).toBe('Abcdefg')
    expect(workspace.canUndoLastBatch.value).toBe(false)
  })

  it('ignores restored review state for a different loaded result identity', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)
    const revision = workspace.currentRevision.value

    workspace.restoreReviewState({
      documentId,
      verificationRunId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      sourceVersion,
      issueStates: {
        [issue.issue_id]: 'rejected'
      },
      selectedSuggestions: {
        [issue.issue_id]: 'stale'
      }
    })

    expect(workspace.issueStates.value).toEqual({
      [issue.issue_id]: 'accepted'
    })
    expect(workspace.selectedSuggestions.value).toEqual({})
    expect(workspace.currentRevision.value).toBe(revision)
  })

  it('supports individual accept, reject, and undo with stable-id summary counts', () => {
    const issueA = buildIssue()
    const issueB = buildIssue({
      issue_id: '44444444-4444-4444-8444-444444444444',
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

  it('reuses an already validated frozen result snapshot without cloning it again', () => {
    const snapshot = createVerificationResultSnapshot(
      buildResult([buildIssue()])
    )
    if (snapshot === null) {
      throw new Error('Expected a valid result snapshot.')
    }
    const workspace = useVerificationWorkspace()

    expect(createVerificationResultSnapshot(snapshot)).toBe(snapshot)
    workspace.loadResult(snapshot)

    expect(workspace.result.value).toBe(snapshot)
  })

  it.each([0, 1])(
    'accepts backend boundary issue confidence %s',
    (confidence) => {
      expect(
        createVerificationResultSnapshot(
          buildResult([buildIssue({ confidence })])
        )
      ).not.toBeNull()
    }
  )

  it('does not publish an unchecked result over the current canonical snapshot', () => {
    const workspace = useVerificationWorkspace()
    const valid = buildResult([buildIssue()])
    workspace.loadResult(valid)
    const prior = workspace.result.value
    const invalid = buildResult([buildIssue()], {
      blocks: [buildBlock({ text: '不匹配' })]
    })

    workspace.loadResult(invalid)

    expect(workspace.result.value).toBe(prior)
    expect(workspace.visibleIssues.value).toHaveLength(1)
  })

  it('rejects invalid block structure even when the result has no issues', () => {
    const workspace = useVerificationWorkspace()

    workspace.loadResult(
      buildResult([], {
        blocks: [buildBlock({ text: '不匹配' })]
      })
    )

    expect(workspace.result.value).toBeNull()
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
      issue_id: '40000000-0000-4000-8000-000000000001',
      start: 1,
      end: 4,
      block_start: 1,
      block_end: 4,
      original: 'bcd',
      suggestion: 'X',
      context: 'abcdef'
    })
    const later = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000002',
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
      issue_id: '40000000-0000-4000-8000-000000000001',
      start: 1,
      end: 4,
      block_start: 1,
      block_end: 4,
      original: 'bcd',
      suggestion: 'X',
      context: 'abcdef'
    })
    const later = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000002',
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

  it('treats a manual edit equal to the current revision as a defensive no-op', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssues([issue.issue_id])
    const revision = workspace.currentRevision.value
    const states = workspace.issueStates.value

    expect(workspace.canUndoLastBatch.value).toBe(true)
    expect(workspace.saveManualEdit(revision?.text ?? '')).toBeNull()

    expect(workspace.currentRevision.value).toBe(revision)
    expect(workspace.issueStates.value).toBe(states)
    expect(workspace.issueStates.value).toEqual({
      [issue.issue_id]: 'accepted'
    })
    expect(workspace.requiresReverification.value).toBe(false)
    expect(workspace.canUndoLastBatch.value).toBe(true)
  })

  it('parents each manual draft to the current authored revision', () => {
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([buildIssue()]))
    workspace.acceptIssue(buildIssue().issue_id)
    const reviewRevision = workspace.currentRevision.value

    const firstManual = workspace.saveManualEdit('第一次手工修改')
    const secondManual = workspace.saveManualEdit('第二次手工修改')

    expect(firstManual).toMatchObject({
      kind: 'manual',
      parent_revision_id: reviewRevision?.revision_id,
      text: '第一次手工修改'
    })
    expect(secondManual).toMatchObject({
      kind: 'manual',
      parent_revision_id: firstManual?.revision_id,
      text: '第二次手工修改'
    })
    expect(secondManual?.revision_id).not.toBe(firstManual?.revision_id)
    expect(Object.isFrozen(secondManual)).toBe(true)
    expect(JSON.parse(JSON.stringify(secondManual))).toEqual(secondManual)
  })

  it('retains the complete immutable revision chain for server persistence', () => {
    const issue = buildIssue()
    const result = buildResult([issue])
    const workspace = useVerificationWorkspace()
    workspace.loadResult(result)

    workspace.acceptIssue(issue.issue_id)
    const review = workspace.currentRevision.value
    workspace.saveManualEdit('手工修订')

    expect(workspace.revisionChain.value).toHaveLength(3)
    expect(workspace.revisionChain.value[0]).toEqual(sourceRevisionFor(result))
    expect(workspace.revisionChain.value[1]).toBe(review)
    expect(workspace.revisionChain.value[2]).toBe(
      workspace.currentRevision.value
    )
    expect(Object.isFrozen(workspace.revisionChain.value)).toBe(true)
    expect(workspace.revisionChain.value[2]).toMatchObject({
      parent_revision_id: review?.revision_id,
      persistence_state: 'draft'
    })
  })

  it('hydrates only a matching draft with the server allocated revision number', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)
    const draft = workspace.currentRevision.value
    if (draft?.revision_id === null || draft?.revision_id === undefined) {
      throw new Error('Expected a draft revision.')
    }

    expect(
      workspace.hydratePersistedRevision({
        ...draft,
        revision_number: 1,
        created_at: '2026-09-03T04:00:00.000Z',
        persistence_state: 'persisted'
      })
    ).toBe(true)

    expect(workspace.currentRevision.value).toMatchObject({
      revision_id: draft.revision_id,
      revision_number: 1,
      created_at: '2026-09-03T04:00:00.000Z',
      persistence_state: 'persisted'
    })
    expect(workspace.revisionChain.value[1]).toBe(
      workspace.currentRevision.value
    )
  })

  it('rejects mismatched persisted hydration without changing the chain', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)
    const before = workspace.revisionChain.value
    const draft = workspace.currentRevision.value
    if (draft?.revision_id === null || draft?.revision_id === undefined) {
      throw new Error('Expected a draft revision.')
    }

    expect(
      workspace.hydratePersistedRevision({
        ...draft,
        text: 'different',
        revision_number: 1,
        persistence_state: 'persisted'
      })
    ).toBe(false)
    expect(workspace.revisionChain.value).toBe(before)
    expect(workspace.currentRevision.value).toBe(draft)
  })

  it('atomically restores a saved manual revision without replaying stale issue offsets', () => {
    const issue = buildIssue()
    const original = useVerificationWorkspace()
    original.loadResult(buildResult([issue]))
    original.acceptIssue(issue.issue_id)
    original.saveManualEdit('会话中的手工修订')
    const savedRevision = JSON.parse(
      JSON.stringify(original.currentRevision.value)
    )

    const result = buildResult([issue])
    const restored = useVerificationWorkspace()
    expect(restored.restoreWorkspaceState(buildSessionV2(result, {
      issueStates: { [issue.issue_id]: 'accepted' },
      selectedSuggestions: { [issue.issue_id]: '陈旧建议' },
      requiresReverification: true,
      currentRevision: savedRevision
    }))).toBe(true)

    expect(restored.currentRevision.value).toEqual(savedRevision)
    expect(restored.currentRevision.value).not.toBe(savedRevision)
    expect(Object.isFrozen(restored.currentRevision.value)).toBe(true)
    expect(restored.requiresReverification.value).toBe(true)
    expect(restored.issueStates.value).toEqual({})
    expect(restored.selectedSuggestions.value).toEqual({})
    expect(restored.visibleIssues.value).toEqual([])
    expect(restored.modifiedText.value).toBe('会话中的手工修订')
    expect(restored.canUndoLastBatch.value).toBe(false)
  })

  it('rejects a manual session revision from a different stable identity', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    const result = buildResult([issue])

    expect(workspace.restoreWorkspaceState(buildSessionV2(result, {
      issueStates: {},
      selectedSuggestions: {},
      requiresReverification: true,
      currentRevision: {
        revision_id: '55555555-5555-4555-8555-555555555555',
        document_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        verification_run_id: runId,
        source_version: sourceVersion,
        revision_number: null,
        created_at: '2026-09-03T02:00:00.000Z',
        parent_revision_id: null,
        persistence_state: 'draft',
        kind: 'manual',
        text: '不属于当前文档'
      }
    }))).toBe(false)

    expect(workspace.result.value).toBeNull()
    expect(workspace.currentRevision.value).toBeNull()
  })

  it('rejects a restored manual draft with a non-UUID revision identity', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    const result = buildResult([issue])

    expect(workspace.restoreWorkspaceState(buildSessionV2(result, {
      issueStates: {},
      selectedSuggestions: {},
      requiresReverification: true,
      currentRevision: {
        revision_id: 'not-a-stable-revision-id',
        document_id: documentId,
        verification_run_id: runId,
        source_version: sourceVersion,
        revision_number: null,
        created_at: '2026-09-03T02:00:00.000Z',
        parent_revision_id: null,
        persistence_state: 'draft',
        kind: 'manual',
        text: '不可信修订'
      }
    }))).toBe(false)

    expect(workspace.result.value).toBeNull()
  })

  it('atomically restores a valid source snapshot', () => {
    const result = buildResult([buildIssue()])
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(buildSessionV2(result))).toBe(true)

    expect(workspace.result.value).toEqual(result)
    expect(workspace.currentRevision.value).toEqual(sourceRevisionFor(result))
    expect(workspace.requiresReverification.value).toBe(false)
    expect(workspace.canUndoLastBatch.value).toBe(false)
  })

  it('rejects out-of-range restored issue confidence without replacing workspace state', () => {
    const priorIssue = buildIssue()
    const priorResult = buildResult([priorIssue])
    const workspace = useVerificationWorkspace()
    workspace.loadResult(priorResult)
    workspace.acceptIssue(priorIssue.issue_id)
    const priorSnapshot = workspace.result.value
    const priorRevision = workspace.currentRevision.value
    const invalidIssue = buildIssue({ confidence: -0.01 })
    const invalidSession = buildSessionV2(buildResult([invalidIssue]))

    expect(workspace.restoreWorkspaceState(invalidSession)).toBe(false)
    expect(workspace.result.value).toBe(priorSnapshot)
    expect(workspace.currentRevision.value).toBe(priorRevision)
    expect(workspace.issueStates.value).toEqual({
      [priorIssue.issue_id]: 'accepted'
    })
    expect(workspace.modifiedText.value).toBe('甲B丙丁')
  })

  it('restores issue-derived canonical and compatibility-localized summaries', () => {
    const canonical = useVerificationWorkspace()
    const localized = useVerificationWorkspace()
    const localizedResult = buildResult([buildIssue()], {
      summary: {
        total: 1,
        by_type: { 错别字: 1 },
        by_severity: { 警告: 1 },
        by_rule: { cn_typo: 1 },
        by_layer: { 字符层: 1 }
      }
    })

    expect(
      canonical.restoreWorkspaceState(
        buildSessionV2(buildResult([buildIssue()]))
      )
    ).toBe(true)
    expect(
      localized.restoreWorkspaceState(buildSessionV2(localizedResult))
    ).toBe(true)
    expect(localized.result.value?.summary).toEqual(localizedResult.summary)
  })

  it.each([
    ['summary total mismatch', (result: any) => {
      result.summary.total = 2
    }],
    ['canonical summary count mismatch', (result: any) => {
      result.summary.by_type = { typo: 0, grammar: 1 }
    }],
    ['localized summary count mismatch', (result: any) => {
      result.summary.by_type = { 错别字: 0, 语法: 1 }
    }],
    ['summary with an extra zero bucket', (result: any) => {
      result.summary.by_severity.info = 0
    }],
    ['summary with a missing bucket', (result: any) => {
      result.summary.by_rule = {}
    }]
  ])('rejects a %s atomically', (_label, mutate) => {
    const saved: any = structuredClone(
      buildSessionV2(buildResult([buildIssue()]))
    )
    mutate(saved.result)
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(saved)).toBe(false)
    expect(workspace.result.value).toBeNull()
    expect(workspace.currentRevision.value).toBeNull()
    expect(workspace.issueStates.value).toEqual({})
  })

  it('restores representative backend-valid PDF metadata', () => {
    const result = buildPdfResult()
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(buildSessionV2(result))).toBe(true)
    expect(workspace.result.value?.pdf_metadata).toEqual(result.pdf_metadata)
    expect(workspace.result.value?.ocr_requirement).toEqual(
      result.ocr_requirement
    )
  })

  it.each([
    ['empty OCR pages', (result: any) => {
      result.pdf_metadata.ocr_requirement.pages = []
      result.ocr_requirement.pages = []
    }],
    ['zero OCR page', (result: any) => {
      result.pdf_metadata.ocr_requirement.pages = [0]
      result.ocr_requirement.pages = [0]
    }],
    ['duplicate OCR pages', (result: any) => {
      result.pdf_metadata.ocr_requirement.pages = [1, 1]
      result.ocr_requirement.pages = [1, 1]
    }],
    ['unsorted OCR pages', (result: any) => {
      result.pdf_metadata.ocr_requirement.pages = [2, 1]
      result.ocr_requirement.pages = [2, 1]
    }],
    ['top-level/PDF OCR mismatch', (result: any) => {
      result.ocr_requirement.mode = 'partial'
    }],
    ['top-level OCR without PDF metadata', (result: any) => {
      delete result.pdf_metadata
    }],
    ['PDF metadata on a non-PDF result', (result: any) => {
      result.file_type = 'txt'
    }]
  ])('rejects %s atomically', (_label, mutate) => {
    const saved: any = structuredClone(buildSessionV2(buildPdfResult()))
    mutate(saved.result)
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(saved)).toBe(false)
    expect(workspace.result.value).toBeNull()
    expect(workspace.currentRevision.value).toBeNull()
  })

  it.each([
    ['a zero-width bbox', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].bbox = [1, 2, 1, 12]
    }],
    ['a zero line direction', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].line_direction = [0, 0]
    }],
    ['a character source range mismatch', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].characters[0].source_end = 2
    }],
    ['an empty character text', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].characters[0].text = ''
    }],
    ['an invalid glyph mapping bbox', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].characters[0].bbox = null
    }],
    ['whitespace mapped as a glyph', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].characters[0].text = ' '
      result.pdf_metadata.pages[0].spans[0].text = ' '
    }],
    ['an empty glyph group id', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].characters[0].group_id = ''
    }],
    ['span character reconstruction mismatch', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].text = 'WW'
    }],
    ['duplicate span glyph group ids', (result: any) => {
      const span = result.pdf_metadata.pages[0].spans[0]
      span.text = 'WW'
      span.characters.push({
        ...span.characters[0],
        source_start: 1,
        source_end: 2
      })
    }],
    ['an empty span font name', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].font_name = ''
    }],
    ['a non-positive span font size', (result: any) => {
      result.pdf_metadata.pages[0].spans[0].font_size = 0
    }],
    ['table cell character reconstruction mismatch', (result: any) => {
      result.pdf_metadata.pages[0].tables[0].rows[0][0].text = 'TT'
    }],
    ['table row shape mismatch', (result: any) => {
      result.pdf_metadata.pages[0].tables[0].row_count = 2
    }],
    ['table column shape mismatch', (result: any) => {
      result.pdf_metadata.pages[0].tables[0].column_count = 2
    }],
    ['table cell coordinate mismatch', (result: any) => {
      result.pdf_metadata.pages[0].tables[0].rows[0][0].cell_index = 1
    }],
    ['out-of-page content coordinates', (result: any) => {
      result.pdf_metadata.pages[0].images[0].bbox = [20, 90, 101, 190]
    }],
    ['invalid PDF page order', (result: any) => {
      result.pdf_metadata.pages[0].page = 2
    }],
    ['an invalid normalized page origin', (result: any) => {
      result.pdf_metadata.pages[0].page_bbox = [1, 0, 100, 200]
    }],
    ['negative page text density', (result: any) => {
      result.pdf_metadata.pages[0].text_density = -0.1
    }],
    ['page image coverage over one', (result: any) => {
      result.pdf_metadata.pages[0].image_coverage = 1.1
    }],
    ['a non-positive warning page', (result: any) => {
      result.pdf_metadata.warnings[0].page = 0
    }],
    ['OCR pages inconsistent with page flags', (result: any) => {
      result.pdf_metadata.pages[0].ocr_required = false
    }],
    ['a non-positive image xref', (result: any) => {
      result.pdf_metadata.pages[0].images[0].xref = 0
    }]
  ])('rejects %s atomically', (_label, mutate) => {
    const saved: any = structuredClone(buildSessionV2(buildPdfResult()))
    mutate(saved.result)
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(saved)).toBe(false)
    expect(workspace.result.value).toBeNull()
    expect(workspace.currentRevision.value).toBeNull()
  })

  it.each([
    ['block style', (result: any) => {
      result.blocks[0].style = { nested: Number.NaN }
    }],
    ['block source locator', (result: any) => {
      result.blocks[0].source_locator = { nested: Number.POSITIVE_INFINITY }
    }],
    ['summary LLM review', (result: any) => {
      result.summary.llm_review = {
        nested: [Number.NEGATIVE_INFINITY]
      }
    }],
    ['PDF metadata', (result: any) => {
      result.pdf_metadata.pages[0].text_density = Number.NaN
    }]
  ])('rejects a non-finite JSON number in %s atomically', (_label, mutate) => {
    const result: any = buildPdfResult()
    mutate(result)
    const workspace = useVerificationWorkspace()

    expect(
      workspace.restoreWorkspaceState(buildSessionV2(result))
    ).toBe(false)
    expect(workspace.result.value).toBeNull()
    expect(workspace.currentRevision.value).toBeNull()
  })

  it('atomically restores and preserves a valid review draft identity', () => {
    const issue = buildIssue()
    const result = buildResult([issue])
    const revisionId = '55555555-5555-4555-8555-555555555555'
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(buildSessionV2(result, {
      issueStates: { [issue.issue_id]: 'accepted' },
      currentRevision: {
        revision_id: revisionId,
        document_id: documentId,
        verification_run_id: runId,
        source_version: sourceVersion,
        revision_number: null,
        created_at: '2026-09-03T02:00:00.000Z',
        parent_revision_id: null,
        persistence_state: 'draft',
        kind: 'review',
        text: '甲B丙丁'
      }
    }))).toBe(true)

    expect(workspace.currentRevision.value).toMatchObject({
      revision_id: revisionId,
      kind: 'review',
      text: '甲B丙丁'
    })
    expect(workspace.issueStates.value).toEqual({
      [issue.issue_id]: 'accepted'
    })
    expect(workspace.requiresReverification.value).toBe(false)
  })

  it('restores a valid accepted-range conflict without publishing a partial revision', () => {
    const first = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000001',
      start: 0,
      end: 3,
      block_start: 0,
      block_end: 3,
      original: 'abc',
      suggestion: 'X',
      context: 'abcdef'
    })
    const second = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000002',
      start: 2,
      end: 5,
      block_start: 2,
      block_end: 5,
      original: 'cde',
      suggestion: 'Y',
      context: 'abcdef'
    })
    const result = buildResult([first, second], { text: 'abcdef' })
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(buildSessionV2(result, {
      issueStates: {
        [first.issue_id]: 'accepted',
        [second.issue_id]: 'accepted'
      }
    }))).toBe(true)

    expect(workspace.hasReplacementConflicts.value).toBe(true)
    expect(workspace.currentRevision.value).toEqual(sourceRevisionFor(result))
    expect(workspace.modifiedText.value).toBe('abcdef')
  })

  it('preserves the last valid review revision when restored decisions now conflict', () => {
    const first = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000001',
      start: 0,
      end: 3,
      block_start: 0,
      block_end: 3,
      original: 'abc',
      suggestion: 'X',
      context: 'abcdef'
    })
    const second = buildIssue({
      issue_id: '40000000-0000-4000-8000-000000000002',
      start: 2,
      end: 5,
      block_start: 2,
      block_end: 5,
      original: 'cde',
      suggestion: 'Y',
      context: 'abcdef'
    })
    const result = buildResult([first, second], { text: 'abcdef' })
    const revisionId = '55555555-5555-4555-8555-555555555555'
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(buildSessionV2(result, {
      issueStates: {
        [first.issue_id]: 'accepted',
        [second.issue_id]: 'accepted'
      },
      currentRevision: {
        revision_id: revisionId,
        document_id: documentId,
        verification_run_id: runId,
        source_version: sourceVersion,
        revision_number: null,
        created_at: '2026-09-03T02:00:00.000Z',
        parent_revision_id: null,
        persistence_state: 'draft',
        kind: 'review',
        text: 'Xdef'
      }
    }))).toBe(true)

    expect(workspace.hasReplacementConflicts.value).toBe(true)
    expect(workspace.currentRevision.value).toMatchObject({
      revision_id: revisionId,
      text: 'Xdef'
    })
    expect(workspace.modifiedText.value).toBe('Xdef')
  })

  it('fully validates legacy sessions before one atomic migration', () => {
    const issue = buildIssue()
    const result = buildResult([issue])
    const reviewWorkspace = useVerificationWorkspace()
    const manualWorkspace = useVerificationWorkspace()

    expect(reviewWorkspace.restoreWorkspaceState({
      result,
      workingText: result.text,
      issueStates: { [issue.issue_id]: 'accepted' },
      selectedSuggestions: { [issue.issue_id]: '' }
    })).toBe(true)
    expect(reviewWorkspace.currentRevision.value).toMatchObject({
      kind: 'review',
      text: '甲丙丁'
    })

    expect(manualWorkspace.restoreWorkspaceState({
      result,
      workingText: '旧会话手工文本',
      issueStates: { [issue.issue_id]: 'accepted' },
      selectedSuggestions: { [issue.issue_id]: '陈旧建议' }
    })).toBe(true)
    expect(manualWorkspace.currentRevision.value).toMatchObject({
      kind: 'manual',
      text: '旧会话手工文本'
    })
    expect(manualWorkspace.issueStates.value).toEqual({})
    expect(manualWorkspace.requiresReverification.value).toBe(true)
  })

  it.each([
    ['shallow block', (saved: any) => {
      delete saved.result.blocks[0].source_locator
    }],
    ['invalid document UUID', (saved: any) => {
      saved.result.document_id = 'not-a-uuid'
    }],
    ['invalid run UUID', (saved: any) => {
      saved.result.verification_run_id = 'not-a-uuid'
    }],
    ['invalid file UUID', (saved: any) => {
      saved.result.file_id = 'file-1'
    }],
    ['invalid issue ownership UUID', (saved: any) => {
      saved.result.issues[0].document_id =
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    }],
    ['invalid result discriminant', (saved: any) => {
      saved.result.execution_mode = 'sometimes'
    }],
    ['invalid issue discriminant', (saved: any) => {
      saved.result.issues[0].severity = 'critical'
    }],
    ['invalid timestamp', (saved: any) => {
      saved.requiresReverification = true
      saved.currentRevision = {
        revision_id: '55555555-5555-4555-8555-555555555555',
        document_id: documentId,
        verification_run_id: runId,
        source_version: sourceVersion,
        revision_number: null,
        created_at: '2026-09-03',
        parent_revision_id: null,
        persistence_state: 'draft',
        kind: 'manual',
        text: '手工文本'
      }
    }],
    ['self parent', (saved: any) => {
      saved.requiresReverification = true
      saved.currentRevision = {
        revision_id: '55555555-5555-4555-8555-555555555555',
        document_id: documentId,
        verification_run_id: runId,
        source_version: sourceVersion,
        revision_number: null,
        created_at: '2026-09-03T02:00:00.000Z',
        parent_revision_id: '55555555-5555-4555-8555-555555555555',
        persistence_state: 'draft',
        kind: 'manual',
        text: '手工文本'
      }
    }],
    ['invalid revision discriminant', (saved: any) => {
      saved.currentRevision.persistence_state = 'temporary'
    }],
    ['invalid persisted number', (saved: any) => {
      saved.currentRevision = {
        revision_id: '55555555-5555-4555-8555-555555555555',
        document_id: documentId,
        verification_run_id: runId,
        source_version: sourceVersion,
        revision_number: 0,
        created_at: '2026-09-03T02:00:00.000Z',
        parent_revision_id: null,
        persistence_state: 'persisted',
        kind: 'review',
        text: '甲乙丙丁'
      }
    }]
  ])('rejects an untrusted %s session without partial publication', (_label, mutate) => {
    const result = buildResult([buildIssue()])
    const saved: any = JSON.parse(JSON.stringify(buildSessionV2(result)))
    mutate(saved)
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(saved)).toBe(false)
    expect(workspace.result.value).toBeNull()
    expect(workspace.currentRevision.value).toBeNull()
    expect(workspace.issueStates.value).toEqual({})
  })

  it('leaves an existing workspace unchanged when atomic session preparation fails', () => {
    const issue = buildIssue()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([issue]))
    workspace.acceptIssue(issue.issue_id)
    const priorResult = workspace.result.value
    const priorRevision = workspace.currentRevision.value
    const priorStates = workspace.issueStates.value
    const invalid = JSON.parse(
      JSON.stringify(buildSessionV2(buildResult([issue])))
    )
    invalid.result.blocks[0].kind = 'unknown'

    expect(workspace.restoreWorkspaceState(invalid)).toBe(false)
    expect(workspace.result.value).toBe(priorResult)
    expect(workspace.currentRevision.value).toBe(priorRevision)
    expect(workspace.issueStates.value).toBe(priorStates)
  })

  it('prunes hostile stable state keys without prototype pollution', () => {
    const result = buildResult([buildIssue()])
    const saved = JSON.parse(
      JSON.stringify(buildSessionV2(result))
        .replace('"issueStates":{}', '"issueStates":{"__proto__":"accepted"}')
        .replace(
          '"selectedSuggestions":{}',
          '"selectedSuggestions":{"constructor":"poison"}'
        )
    )
    const workspace = useVerificationWorkspace()

    expect(workspace.restoreWorkspaceState(saved)).toBe(true)
    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.selectedSuggestions.value).toEqual({})
    expect(({} as Record<string, unknown>).polluted).toBeUndefined()
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

  it.each([
    ['null', null],
    ['omitted', undefined]
  ])('normalizes %s issue alternatives to one frozen canonical array', (_label, alternatives) => {
    const issue = buildIssue()
    ;(issue as unknown as { alternatives?: string[] | null }).alternatives =
      alternatives
    const raw = buildResult([issue])
    const snapshot = createVerificationResultSnapshot(raw)

    expect(snapshot?.issues[0]?.alternatives).toEqual([])
    expect(Object.isFrozen(snapshot?.issues[0]?.alternatives)).toBe(true)
  })

  it('rejects an over-limit issue array before reading issue entries', () => {
    const result = buildResult([])
    const issues = new Proxy(
      new Array(MAX_VERIFICATION_ISSUES + 1),
      {
        get(target, property, receiver) {
          if (property === Symbol.iterator) {
            throw new Error('issue entries must not be read')
          }
          return Reflect.get(target, property, receiver)
        }
      }
    )

    expect(
      createVerificationResultSnapshot({
        ...result,
        issues,
        summary: {
          total: MAX_VERIFICATION_ISSUES + 1,
          by_type: {},
          by_severity: {},
          by_rule: {},
          by_layer: {}
        }
      })
    ).toBeNull()
  })

  it('precomputes document code-point offsets once for many issue validations', () => {
    const issueCount = 500
    const text = '错对'.repeat(issueCount)
    const issues = Array.from({ length: issueCount }, (_, index) => {
      const start = index * 2
      return buildIssue({
        issue_id: `33333333-3333-4333-8333-${String(index).padStart(12, '0')}`,
        start,
        end: start + 1,
        block_start: start,
        block_end: start + 1,
        original: '错'
      })
    })
    const raw = buildResult(issues, { text })
    const originalIterator = String.prototype[Symbol.iterator]
    let documentCharacterReads = 0
    const iterator = vi
      .spyOn(String.prototype, Symbol.iterator)
      .mockImplementation(function* (
        this: string
      ): Generator<string, undefined, unknown> {
        const value = String(this)
        for (const character of originalIterator.call(value)) {
          if (value === text) {
            documentCharacterReads += 1
          }
          yield character
        }
        return undefined
      })

    try {
      expect(createVerificationResultSnapshot(raw)).not.toBeNull()
    } finally {
      iterator.mockRestore()
    }

    expect(documentCharacterReads).toBeLessThan(20_000)
  })

  it('keeps exact unmatched-quote acceptance anchored without mutating a prefix', () => {
    const text = '前😀缀「未闭'
    const quote = buildIssue({
      start: 3,
      end: 4,
      block_start: 3,
      block_end: 4,
      original: '「',
      suggestion: null,
      alternatives: [],
      type: 'punctuation',
      layer: 'format',
      message: '引号未配对',
      description: '引号未配对',
      rule_id: 'unmatched_quote',
      auto_fixable: false,
      context: text
    })
    const workspace = useVerificationWorkspace()
    workspace.loadResult(buildResult([quote], { text }))

    workspace.acceptIssue(quote.issue_id)

    expect(workspace.modifiedText.value).toBe(text)
    expect(workspace.currentRevision.value?.text).toBe(text)
    expect(workspace.issueStates.value[quote.issue_id]).toBe('accepted')
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
