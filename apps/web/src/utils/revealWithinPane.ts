export function revealWithinPane(
  target: HTMLElement,
  pane: HTMLElement | null
): void {
  if (!pane || pane.clientHeight === 0) {
    return
  }
  const paneBounds = pane.getBoundingClientRect()
  const targetBounds = target.getBoundingClientRect()
  const paneTop = paneBounds.top + pane.clientTop
  const bottom = paneTop + pane.clientHeight
  const top = paneTop
  if (targetBounds.top < top) {
    pane.scrollTop += targetBounds.top - top
  } else if (targetBounds.bottom > bottom) {
    pane.scrollTop += Math.min(
      targetBounds.bottom - bottom,
      targetBounds.top - top
    )
  }
}
