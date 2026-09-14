export function revealWithinPane(
  target: HTMLElement,
  pane: HTMLElement | null,
  revealHorizontal = false,
  verticalAlignment: 'nearest' | 'center' = 'nearest'
): void {
  if (!pane || pane.clientHeight === 0) {
    return
  }
  const paneBounds = pane.getBoundingClientRect()
  const targetBounds = target.getBoundingClientRect()
  const paneTop = paneBounds.top + pane.clientTop
  const bottom = paneTop + pane.clientHeight
  const top = paneTop
  if (verticalAlignment === 'center') {
    pane.scrollTop += (targetBounds.top + targetBounds.bottom) / 2 - (top + pane.clientHeight / 2)
  } else if (targetBounds.top < top) {
    pane.scrollTop += targetBounds.top - top
  } else if (targetBounds.bottom > bottom) {
    pane.scrollTop += Math.min(
      targetBounds.bottom - bottom,
      targetBounds.top - top
    )
  }
  if (revealHorizontal) {
    const left = paneBounds.left + pane.clientLeft
    const right = left + pane.clientWidth
    if (targetBounds.left < left) {
      pane.scrollLeft += targetBounds.left - left
    } else if (targetBounds.right > right) {
      pane.scrollLeft += Math.min(targetBounds.right - right, targetBounds.left - left)
    }
  }
}
