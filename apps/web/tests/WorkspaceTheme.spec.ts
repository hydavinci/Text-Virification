import { describe, expect, it } from 'vitest'

import {
  applyStoredWorkspaceTheme,
  persistWorkspaceTheme
} from '../src/composables/useWorkspaceTheme'

describe('workspace theme persistence', () => {
  it('applies a stored dark theme before the app mounts', () => {
    const root = document.createElement('html')
    const storage = {
      getItem: () => 'dark'
    } as Pick<Storage, 'getItem'>

    expect(applyStoredWorkspaceTheme(storage, root)).toBe('dark')
    expect(root.dataset.theme).toBe('dark')
  })

  it('falls back safely and persists explicit theme changes', () => {
    const root = document.createElement('html')
    const values = new Map<string, string>()
    const storage = {
      getItem: () => 'unexpected',
      setItem: (key: string, value: string) => values.set(key, value)
    } as Pick<Storage, 'getItem' | 'setItem'>

    expect(applyStoredWorkspaceTheme(storage, root)).toBe('light')
    persistWorkspaceTheme('dark', storage, root)

    expect(root.dataset.theme).toBe('dark')
    expect(values.get('text-verification-theme')).toBe('dark')
  })
})
