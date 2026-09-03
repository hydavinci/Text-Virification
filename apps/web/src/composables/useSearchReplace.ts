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

const MAX_FOLDED_QUERY_LENGTH = 4096

function foldSearchValue(value: string): string[] {
  return Array.from(
    value
      .normalize('NFKD')
      .toLocaleUpperCase('und')
      .toLocaleLowerCase('und')
      .normalize('NFKD')
  )
}

function foldedValuesEqual(
  candidate: readonly string[],
  query: readonly string[]
): boolean {
  if (candidate.length !== query.length) {
    return false
  }
  for (let offset = 0; offset < query.length; offset += 1) {
    if (candidate[offset] !== query[offset]) {
      return false
    }
  }
  return true
}

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
    if (caseSensitive.value) {
      let start = 0
      while (start + queryCharacters.length <= textCharacters.length) {
        const candidate = textCharacters
          .slice(start, start + queryCharacters.length)
          .join('')
        if (candidate === query.value) {
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
    }

    const foldedQuery = foldSearchValue(query.value)
    if (
      foldedQuery.length === 0 ||
      foldedQuery.length > MAX_FOLDED_QUERY_LENGTH
    ) {
      return Object.freeze([])
    }

    let originalStart = 0
    while (originalStart < textCharacters.length) {
      let originalEnd = originalStart + 1
      let matchedEnd: number | null = null
      while (originalEnd <= textCharacters.length) {
        const foldedCandidate = foldSearchValue(
          textCharacters.slice(originalStart, originalEnd).join('')
        )
        if (foldedCandidate.length > foldedQuery.length) {
          break
        }
        if (foldedValuesEqual(foldedCandidate, foldedQuery)) {
          matchedEnd = originalEnd
          break
        }
        originalEnd += 1
      }
      if (matchedEnd === null) {
        originalStart += 1
      } else {
        found.push({ start: originalStart, end: matchedEnd })
        originalStart = matchedEnd
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
    if (nextText === toValue(text)) {
      return false
    }
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
    const nextText = segments.join('')
    if (nextText === toValue(text)) {
      return false
    }
    onReplace(nextText, {
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
