import {
  computed,
  ref,
  toValue,
  watch,
  type MaybeRefOrGetter
} from 'vue'
import { graphemeSegments } from 'unicode-segmenter/grapheme'

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
const nativeGraphemeSegmenter =
  typeof Intl.Segmenter === 'function'
    ? new Intl.Segmenter('und', { granularity: 'grapheme' })
    : null

interface GraphemeSegment {
  segment: string
  start: number
  end: number
}

function* segmentGraphemes(value: string): Generator<GraphemeSegment> {
  const segments =
    nativeGraphemeSegmenter === null
      ? graphemeSegments(value)
      : nativeGraphemeSegmenter.segment(value)
  let start = 0

  for (const { segment } of segments) {
    let end = start
    for (const _character of segment) {
      end += 1
    }
    yield { segment, start, end }
    start = end
  }
}

function foldSearchValue(value: string): string {
  return value
    .normalize('NFKD')
    .toLocaleUpperCase('und')
    .toLocaleLowerCase('und')
    .normalize('NFKD')
}

function appendFoldedSearchValue(
  characters: string[],
  value: string,
  maximumLength = Number.POSITIVE_INFINITY
): boolean {
  for (const character of foldSearchValue(value)) {
    if (characters.length >= maximumLength) {
      return false
    }
    characters.push(character)
  }
  return true
}

function foldValueByGrapheme(value: string): string[] | null {
  const characters: string[] = []

  for (const { segment } of segmentGraphemes(value)) {
    if (
      !appendFoldedSearchValue(
        characters,
        segment,
        MAX_FOLDED_QUERY_LENGTH
      )
    ) {
      return null
    }
  }

  return characters
}

interface FoldedGraphemeText {
  characters: readonly string[]
  originalStarts: readonly (number | undefined)[]
  originalEnds: readonly (number | undefined)[]
}

function foldTextByGrapheme(value: string): FoldedGraphemeText {
  const characters: string[] = []
  const originalStarts: (number | undefined)[] = []
  const originalEnds: (number | undefined)[] = []

  for (const { segment, start, end } of segmentGraphemes(value)) {
    const foldedStart = characters.length
    originalStarts[foldedStart] = start
    appendFoldedSearchValue(characters, segment)
    originalEnds[characters.length] = end
  }

  return {
    characters,
    originalStarts,
    originalEnds
  }
}

function buildKmpPrefixTable(pattern: readonly string[]): number[] {
  const prefixTable = new Array<number>(pattern.length).fill(0)
  let prefixLength = 0

  for (let offset = 1; offset < pattern.length; offset += 1) {
    while (
      prefixLength > 0 &&
      pattern[offset] !== pattern[prefixLength]
    ) {
      prefixLength = prefixTable[prefixLength - 1] ?? 0
    }
    if (pattern[offset] === pattern[prefixLength]) {
      prefixLength += 1
    }
    prefixTable[offset] = prefixLength
  }

  return prefixTable
}

function findInsensitiveMatches(
  originalText: string,
  foldedQuery: readonly string[]
): SearchMatch[] {
  const {
    characters: foldedText,
    originalStarts,
    originalEnds
  } = foldTextByGrapheme(originalText)
  const prefixTable = buildKmpPrefixTable(foldedQuery)
  const found: SearchMatch[] = []
  let matchedLength = 0
  let acceptedThrough = 0

  for (let offset = 0; offset < foldedText.length; offset += 1) {
    while (
      matchedLength > 0 &&
      foldedText[offset] !== foldedQuery[matchedLength]
    ) {
      matchedLength = prefixTable[matchedLength - 1] ?? 0
    }
    if (foldedText[offset] === foldedQuery[matchedLength]) {
      matchedLength += 1
    }
    if (matchedLength !== foldedQuery.length) {
      continue
    }

    const foldedEnd = offset + 1
    const foldedStart = foldedEnd - foldedQuery.length
    const originalStart = originalStarts[foldedStart]
    const originalEnd = originalEnds[foldedEnd]
    if (
      foldedStart >= acceptedThrough &&
      originalStart !== undefined &&
      originalEnd !== undefined
    ) {
      found.push({
        start: originalStart,
        end: originalEnd
      })
      acceptedThrough = foldedEnd
    }
    matchedLength = prefixTable[matchedLength - 1] ?? 0
  }

  return found
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
    if (query.value.length === 0) {
      return Object.freeze([])
    }

    const originalText = toValue(text)
    if (caseSensitive.value) {
      const queryCharacters = Array.from(query.value)
      const textCharacters = Array.from(originalText)
      const found: SearchMatch[] = []
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

    const foldedQuery = foldValueByGrapheme(query.value)
    if (foldedQuery === null || foldedQuery.length === 0) {
      return Object.freeze([])
    }
    return Object.freeze(
      findInsensitiveMatches(originalText, foldedQuery).map((match) =>
        Object.freeze(match)
      )
    )
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
