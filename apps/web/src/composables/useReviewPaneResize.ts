import { computed, ref, watch } from 'vue'

export function useReviewPaneResize() {
  const grid = ref<HTMLElement | null>(null)
  const containerWidth = ref(0)
  const preferredWidth = ref(320)
  const isResizing = ref(false)
  const minWidth = 260
  const maxWidth = computed(() =>
    containerWidth.value ? Math.max(minWidth, Math.min(640, containerWidth.value - 372)) : 640
  )
  const width = computed(() => Math.min(maxWidth.value, Math.max(minWidth, preferredWidth.value)))
  let drag: { pointerId: number; x: number; width: number } | null = null

  watch(grid, (element, _, onCleanup) => {
    if (!element) return
    const measure = () => { containerWidth.value = element.getBoundingClientRect().width }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    onCleanup(() => {
      observer.disconnect()
      drag = null
      isResizing.value = false
    })
  }, { flush: 'post' })

  function setWidth(value: number): void {
    preferredWidth.value = Math.round(Math.min(maxWidth.value, Math.max(minWidth, value)))
  }

  function start(event: PointerEvent): void {
    if (event.button !== 0 || drag || !(event.currentTarget instanceof HTMLElement)) return
    event.preventDefault()
    event.currentTarget.focus({ preventScroll: true })
    event.currentTarget.setPointerCapture(event.pointerId)
    drag = { pointerId: event.pointerId, x: event.clientX, width: width.value }
    isResizing.value = true
  }

  function move(event: PointerEvent): void {
    if (drag?.pointerId === event.pointerId) {
      setWidth(drag.width + drag.x - event.clientX)
    }
  }

  function stop(event: PointerEvent): void {
    if (drag?.pointerId === event.pointerId) {
      drag = null
      isResizing.value = false
    }
  }

  function reset(): void {
    preferredWidth.value = 320
  }

  function onKeydown(event: KeyboardEvent): void {
    switch (event.key) {
      case 'ArrowLeft': setWidth(width.value + 16); break
      case 'ArrowRight': setWidth(width.value - 16); break
      case 'Home': setWidth(minWidth); break
      case 'End': setWidth(maxWidth.value); break
      case 'Enter': reset(); break
      default: return
    }
    event.preventDefault()
  }

  return { grid, width, minWidth, maxWidth, isResizing, start, move, stop, reset, onKeydown }
}
