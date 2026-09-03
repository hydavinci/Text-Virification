import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useSearchReplace } from '../src/composables/useSearchReplace'

describe('useSearchReplace', () => {
  it('finds literal metacharacters with explicit code-point offsets', () => {
    const text = ref('a.b a?b a.b')
    const search = useSearchReplace({ text })

    search.query.value = 'a.b'

    expect(search.matches.value).toEqual([
      { start: 0, end: 3 },
      { start: 8, end: 11 }
    ])
    expect(search.currentMatch.value).toEqual({ start: 0, end: 3 })
  })

  it('uses deterministic non-overlapping matches for overlapping-looking queries', () => {
    const search = useSearchReplace({ text: () => 'aaaa' })

    search.query.value = 'aa'

    expect(search.matches.value).toEqual([
      { start: 0, end: 2 },
      { start: 2, end: 4 }
    ])
  })

  it('handles astral text and Unicode case-insensitive matching without transformed offsets', () => {
    const search = useSearchReplace({ text: () => '😀A😀a Σ σ ς' })

    search.query.value = '😀a'
    expect(search.matches.value).toEqual([
      { start: 0, end: 2 },
      { start: 2, end: 4 }
    ])

    search.query.value = 'σ'
    expect(search.matches.value).toEqual([
      { start: 5, end: 6 },
      { start: 7, end: 8 },
      { start: 9, end: 10 }
    ])
  })

  it('maps length-changing Unicode folds back to original code-point ranges', () => {
    const ligatures = useSearchReplace({ text: () => 'oﬃce office' })
    ligatures.query.value = 'office'
    expect(ligatures.matches.value).toEqual([
      { start: 0, end: 4 },
      { start: 5, end: 11 }
    ])
    ligatures.query.value = 'oﬃce'
    expect(ligatures.matches.value).toEqual([
      { start: 0, end: 4 },
      { start: 5, end: 11 }
    ])

    const sharpS = useSearchReplace({ text: () => 'Straße STRASSE' })
    sharpS.query.value = 'STRASSE'
    expect(sharpS.matches.value).toEqual([
      { start: 0, end: 6 },
      { start: 7, end: 14 }
    ])
    sharpS.query.value = 'Straße'
    expect(sharpS.matches.value).toEqual([
      { start: 0, end: 6 },
      { start: 7, end: 14 }
    ])
  })

  it('matches composed and decomposed equivalents in both directions', () => {
    const search = useSearchReplace({ text: () => 'é e\u0301' })

    search.query.value = 'e\u0301'
    expect(search.matches.value).toEqual([
      { start: 0, end: 1 },
      { start: 2, end: 4 }
    ])

    search.query.value = 'é'
    expect(search.matches.value).toEqual([
      { start: 0, end: 1 },
      { start: 2, end: 4 }
    ])
  })

  it('matches canonical equivalents when combining marks reorder across original boundaries', () => {
    const first = useSearchReplace({ text: () => 'a\u0315\u0300 à\u0315' })

    first.query.value = 'à\u0315'
    expect(first.matches.value).toEqual([
      { start: 0, end: 3 },
      { start: 4, end: 6 }
    ])

    first.query.value = 'a\u0315\u0300'
    expect(first.matches.value).toEqual([
      { start: 0, end: 3 },
      { start: 4, end: 6 }
    ])

    const second = useSearchReplace({
      text: () => 'q\u0307\u0323 q\u0323\u0307'
    })
    second.query.value = 'q\u0323\u0307'
    expect(second.matches.value).toEqual([
      { start: 0, end: 3 },
      { start: 4, end: 7 }
    ])
  })

  it('does not match a base inside an accented grapheme', () => {
    const search = useSearchReplace({ text: () => 'a\u0301 á a' })

    search.query.value = 'a'
    expect(search.matches.value).toEqual([{ start: 5, end: 6 }])
  })

  it('does not match a combining mark attached to a base', () => {
    const search = useSearchReplace({ text: () => 'a\u0301 á' })

    search.query.value = '\u0301'
    expect(search.matches.value).toEqual([])
  })

  it('replaces the exact original grapheme range without leaving combining marks', () => {
    const text = ref('x a\u0301 y')
    const onReplace = vi.fn((nextText: string) => {
      text.value = nextText
    })
    const search = useSearchReplace({ text, onReplace })

    search.query.value = 'á'
    expect(search.matches.value).toEqual([{ start: 2, end: 4 }])

    search.replacement.value = 'Z'
    expect(search.replaceCurrent()).toBe(true)
    expect(text.value).toBe('x Z y')
    expect(onReplace).toHaveBeenCalledWith('x Z y', {
      kind: 'current',
      count: 1
    })
  })

  it('does not replace a base or combining mark inside an accented grapheme', () => {
    const text = ref('a\u0301')
    const onReplace = vi.fn()
    const search = useSearchReplace({ text, onReplace })
    search.replacement.value = 'X'

    search.query.value = 'a'
    expect(search.replaceAll()).toBe(false)

    search.query.value = '\u0301'
    expect(search.replaceAll()).toBe(false)
    expect(text.value).toBe('a\u0301')
    expect(onReplace).not.toHaveBeenCalled()
  })

  it('folds each text grapheme and the complete query only once', () => {
    const originalNormalize = String.prototype.normalize
    const normalizeSpy = vi
      .spyOn(String.prototype, 'normalize')
      .mockImplementation(function (
        this: string,
        form?: string
      ) {
        return originalNormalize.call(this, form)
      })
    const search = useSearchReplace({
      text: () => `${'a'.repeat(10_000)}b`
    })

    try {
      search.query.value = 'a'.repeat(512)
      expect(search.matches.value).toHaveLength(19)
      expect(normalizeSpy).toHaveBeenCalledTimes(2 * (10_001 + 1))
    } finally {
      normalizeSpy.mockRestore()
    }
  })

  it('replaces whole original ranges after cross-boundary canonical reordering', () => {
    const text = ref('😀a\u0315\u0300 q\u0307\u0323')
    const onReplace = vi.fn((nextText: string) => {
      text.value = nextText
    })
    const search = useSearchReplace({ text, onReplace })

    search.query.value = 'à\u0315'
    search.replacement.value = 'A'
    expect(search.replaceCurrent()).toBe(true)
    expect(text.value).toBe('😀A q\u0307\u0323')

    search.query.value = 'q\u0323\u0307'
    search.replacement.value = 'Q'
    expect(search.replaceAll()).toBe(true)
    expect(text.value).toBe('😀A Q')
    expect(onReplace).toHaveBeenCalledTimes(2)
  })

  it('rejects matches ending inside a folded expansion and keeps exact case-sensitive matching', () => {
    const search = useSearchReplace({ text: () => 'ﬃ ffi' })

    search.query.value = 'f'
    expect(search.matches.value).toEqual([
      { start: 2, end: 3 },
      { start: 3, end: 4 }
    ])

    search.query.value = 'fi'
    expect(search.matches.value).toEqual([{ start: 3, end: 5 }])

    search.query.value = 'ffi'
    expect(search.matches.value).toEqual([
      { start: 0, end: 1 },
      { start: 2, end: 5 }
    ])

    search.caseSensitive.value = true
    expect(search.matches.value).toEqual([{ start: 2, end: 5 }])
  })

  it('cycles previous and next navigation at document boundaries', () => {
    const search = useSearchReplace({ text: () => 'a-a-a' })
    search.query.value = 'a'

    search.previous()
    expect(search.activeMatchIndex.value).toBe(2)
    search.next()
    expect(search.activeMatchIndex.value).toBe(0)
    search.next()
    expect(search.activeMatchIndex.value).toBe(1)
  })

  it('supports empty replacement deletion and creates one replacement action', () => {
    const text = ref('aba')
    const onReplace = vi.fn((nextText: string) => {
      text.value = nextText
    })
    const search = useSearchReplace({ text, onReplace })
    search.query.value = 'b'
    search.replacement.value = ''

    expect(search.replaceCurrent()).toBe(true)
    expect(text.value).toBe('aa')
    expect(onReplace).toHaveBeenCalledOnce()
    expect(onReplace).toHaveBeenCalledWith('aa', {
      kind: 'current',
      count: 1
    })
  })

  it('replaces all current-revision matches in one action and ignores an empty query', () => {
    const text = ref('Aa😀aa')
    const onReplace = vi.fn((nextText: string) => {
      text.value = nextText
    })
    const search = useSearchReplace({ text, onReplace })

    expect(search.replaceAll()).toBe(false)
    expect(onReplace).not.toHaveBeenCalled()

    search.query.value = 'aa'
    search.replacement.value = 'X'
    expect(search.replaceAll()).toBe(true)
    expect(text.value).toBe('X😀X')
    expect(onReplace).toHaveBeenCalledOnce()
    expect(onReplace).toHaveBeenCalledWith('X😀X', {
      kind: 'all',
      count: 2
    })
  })

  it('does not publish replace-current or replace-all actions when text is unchanged', () => {
    const text = ref('same same')
    const onReplace = vi.fn()
    const search = useSearchReplace({ text, onReplace })
    search.query.value = 'same'
    search.replacement.value = 'same'

    expect(search.replaceCurrent()).toBe(false)
    expect(search.replaceAll()).toBe(false)
    expect(onReplace).not.toHaveBeenCalled()
    expect(search.activeMatchIndex.value).toBe(0)
  })
})
