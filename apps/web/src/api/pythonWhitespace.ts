const PYTHON_WHITESPACE_CHARACTER = /[\u001c-\u001f\p{White_Space}]/u
const PYTHON_WHITESPACE_EDGES =
  /^[\u001c-\u001f\p{White_Space}]+|[\u001c-\u001f\p{White_Space}]+$/gu

export function isPythonWhitespace(value: string): boolean {
  return PYTHON_WHITESPACE_CHARACTER.test(value)
}

export function stripPythonWhitespace(value: string): string {
  return value.replace(PYTHON_WHITESPACE_EDGES, '')
}
