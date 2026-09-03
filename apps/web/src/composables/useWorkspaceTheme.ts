export type WorkspaceTheme = 'light' | 'dark'

const THEME_KEY = 'text-verification-theme'

export function applyStoredWorkspaceTheme(
  storage: Pick<Storage, 'getItem'>,
  root: HTMLElement
): WorkspaceTheme {
  let theme: WorkspaceTheme = 'light'
  try {
    theme = storage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    theme = 'light'
  }
  root.dataset.theme = theme
  return theme
}

export function persistWorkspaceTheme(
  theme: WorkspaceTheme,
  storage: Pick<Storage, 'setItem'>,
  root: HTMLElement
): void {
  root.dataset.theme = theme
  try {
    storage.setItem(THEME_KEY, theme)
  } catch {
    // Theme application remains valid even when persistence is unavailable.
  }
}
