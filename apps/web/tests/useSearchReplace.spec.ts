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
})
