import {
  computed,
  ref,
  toValue,
  watch,
  type MaybeRefOrGetter
} from 'vue'

export interface SearchMatch {
  start: number
  end: number
}

export interface SearchReplacement {
  kind: 'current' | 'all'
  count: number
}

interface UseSearchReplaceOptions {
  text: MaybeRefOrGetter<string>
  onReplace?: (text: string, replacement: SearchReplacement) => void
}

const caseInsensitiveCollator = new Intl.Collator('und', {
  usage: 'search',
  sensitivity: 'accent'
})

export function useSearchReplace({
  text,
  onReplace
}: UseSearchReplaceOptions) {
  const query = ref('')
  const replacement = ref('')
  const caseSensitive = ref(false)
  const activeMatchIndex = ref(0)

  const matches = computed<readonly SearchMatch[]>(() => {
    const queryCharacters = Array.from(query.value)
    if (queryCharacters.length === 0) {
      return Object.freeze([])
    }

    const textCharacters = Array.from(toValue(text))
    const found: SearchMatch[] = []
    let start = 0
    while (start + queryCharacters.length <= textCharacters.length) {
      const candidate = textCharacters
        .slice(start, start + queryCharacters.length)
        .join('')
      const isMatch = caseSensitive.value
        ? candidate === query.value
        : caseInsensitiveCollator.compare(candidate, query.value) === 0
      if (isMatch) {
        found.push({
          start,
          end: start + queryCharacters.length
        })
        start += queryCharacters.length
      } else {
        start += 1
      }
    }
    return Object.freeze(found.map((match) => Object.freeze(match)))
  })

  const currentMatch = computed<SearchMatch | null>(() => {
    if (matches.value.length === 0) {
      return null
    }
    return matches.value[
      Math.min(activeMatchIndex.value, matches.value.length - 1)
    ] ?? null
  })

  const statusText = computed(() =>
    matches.value.length === 0
      ? '未找到匹配项'
      : `第 ${Math.min(activeMatchIndex.value, matches.value.length - 1) + 1} 项，共 ${matches.value.length} 项`
  )

  function previous(): void {
    if (matches.value.length === 0) {
      activeMatchIndex.value = 0
      return
    }
    activeMatchIndex.value =
      (activeMatchIndex.value - 1 + matches.value.length) %
      matches.value.length
  }

  function next(): void {
    if (matches.value.length === 0) {
      activeMatchIndex.value = 0
      return
    }
    activeMatchIndex.value =
      (activeMatchIndex.value + 1) % matches.value.length
  }

  function replaceCurrent(): boolean {
    const match = currentMatch.value
    if (match === null || onReplace === undefined) {
      return false
    }
    const characters = Array.from(toValue(text))
    const nextText = [
      ...characters.slice(0, match.start),
      replacement.value,
      ...characters.slice(match.end)
    ].join('')
    onReplace(nextText, { kind: 'current', count: 1 })
    activeMatchIndex.value = 0
    return true
  }

  function replaceAll(): boolean {
    const currentMatches = matches.value
    if (currentMatches.length === 0 || onReplace === undefined) {
      return false
    }
    const characters = Array.from(toValue(text))
    const segments: string[] = []
    let cursor = 0
    for (const match of currentMatches) {
      segments.push(
        characters.slice(cursor, match.start).join(''),
        replacement.value
      )
      cursor = match.end
    }
    segments.push(characters.slice(cursor).join(''))
    onReplace(segments.join(''), {
      kind: 'all',
      count: currentMatches.length
    })
    activeMatchIndex.value = 0
    return true
  }

  watch(
    [() => toValue(text), query, caseSensitive],
    () => {
      activeMatchIndex.value = 0
    },
    { flush: 'sync' }
  )

  return {
    query,
    replacement,
    caseSensitive,
    matches,
    activeMatchIndex,
    currentMatch,
    statusText,
    previous,
    next,
    replaceCurrent,
    replaceAll
  }
}
