import type { Directive } from 'vue'

interface SelectMenu {
  refresh: () => void
  dispose: () => void
}

const menus = new WeakMap<HTMLSelectElement, SelectMenu>()
let nextId = 0

function attach(select: HTMLSelectElement): SelectMenu {
  const menu = document.createElement('div')
  menu.id = `select-menu-${++nextId}`
  menu.className = 'ui-select-menu'
  menu.setAttribute('role', 'listbox')
  let open = false
  let active = -1
  let prefix = ''
  let typedAt = 0
  const hiddenOptions = new Map<HTMLOptionElement, string | null>()

  const enabled = () => [...select.options].map((option, index) => ({ option, index }))
    .filter(({ option }) => !option.disabled &&
      !(option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled))

  function activate(index: number, scroll = false): void {
    active = index
    for (const [position, child] of [...menu.children].entries()) {
      child.classList.toggle('is-active', position === active)
    }
    const option = menu.children[active]
    if (option) {
      select.setAttribute('aria-activedescendant', option.id)
      if (scroll) option.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    }
  }

  function close(): void {
    open = false
    menu.remove()
    for (const [option, previous] of hiddenOptions) {
      if (previous === null) option.removeAttribute('aria-hidden')
      else option.setAttribute('aria-hidden', previous)
    }
    hiddenOptions.clear()
    select.setAttribute('aria-expanded', 'false')
    select.removeAttribute('aria-controls')
    select.removeAttribute('aria-activedescendant')
    document.removeEventListener('pointerdown', dismissOutside, true)
    window.removeEventListener('scroll', repositionOnScroll, true)
    window.removeEventListener('resize', close)
  }

  function refresh(): void {
    if (!open) return
    if (select.matches(':disabled')) {
      close()
      return
    }
    const available = enabled().map(({ index }) => index)
    if (!available.length) {
      close()
      return
    }
    menu.replaceChildren(...[...select.options].map((option, index) => {
      if (!hiddenOptions.has(option)) hiddenOptions.set(option, option.getAttribute('aria-hidden'))
      option.setAttribute('aria-hidden', 'true')
      const item = document.createElement('div')
      item.id = `${menu.id}-${index}`
      item.className = 'ui-select-option'
      item.dataset.optionIndex = String(index)
      item.textContent = option.label
      item.setAttribute('role', 'option')
      item.setAttribute('aria-selected', String(index === select.selectedIndex))
      item.setAttribute('aria-disabled', String(!available.includes(index)))
      return item
    }))
    activate(available.includes(active) ? active : (available[0] ?? -1))
  }

  function position(): void {
    const bounds = select.getBoundingClientRect()
    const width = Math.min(bounds.width, window.innerWidth - 16)
    Object.assign(menu.style, {
      top: `${bounds.bottom + 2}px`,
      left: `${Math.max(8, Math.min(bounds.left, window.innerWidth - width - 8))}px`,
      width: `${width}px`,
      maxHeight: `${Math.max(0, Math.min(240, window.innerHeight - bounds.bottom - 8))}px`
    })
  }

  function show(): void {
    if (select.matches(':disabled') || !enabled().length) return
    if (window.innerHeight - select.getBoundingClientRect().bottom < 120) {
      select.scrollIntoView({ block: 'center', inline: 'nearest' })
    }
    position()
    menu.setAttribute('aria-label',
      select.getAttribute('aria-label') || select.labels?.[0]?.textContent?.trim() || '选择选项')
    open = true
    active = select.selectedIndex
    prefix = ''
    refresh()
    const container = select.closest('[role="dialog"]') || document.body
    container.append(menu)
    select.setAttribute('aria-expanded', 'true')
    select.setAttribute('aria-controls', menu.id)
    activate(active, true)
    document.addEventListener('pointerdown', dismissOutside, true)
    window.addEventListener('scroll', repositionOnScroll, true)
    window.addEventListener('resize', close)
  }

  function choose(): void {
    if (!enabled().some(({ index }) => index === active) || select.matches(':disabled')) return
    const changed = select.selectedIndex !== active
    select.selectedIndex = active
    close()
    if (changed) {
      select.dispatchEvent(new Event('input', { bubbles: true }))
      select.dispatchEvent(new Event('change', { bubbles: true }))
    }
  }

  function dismissOutside(event: PointerEvent): void {
    if (event.target instanceof Node && event.target !== select && !menu.contains(event.target)) close()
  }

  function repositionOnScroll(event: Event): void {
    if (event.target instanceof Node && menu.contains(event.target)) return
    const bounds = select.getBoundingClientRect()
    if (bounds.bottom <= 0 || bounds.top >= window.innerHeight) close()
    else position()
  }

  function pointerDown(event: PointerEvent): void {
    if (event.button !== 0 || select.matches(':disabled')) return
    event.preventDefault()
    select.focus({ preventScroll: true })
    if (open) close()
    else show()
  }

  function preventNative(event: Event): void {
    event.preventDefault()
  }

  function click(event: MouseEvent): void {
    event.preventDefault()
    if (event.detail === 0) {
      if (open) close()
      else show()
    }
  }

  function keydown(event: KeyboardEvent): void {
    if (select.matches(':disabled') || event.isComposing) return
    if (open && event.key === 'Tab') {
      choose()
      return
    }
    if (open && event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close()
      return
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(event.key)) {
      event.preventDefault()
      event.stopPropagation()
      if (!open) {
        show()
        return
      }
      if (event.key === 'Enter' || event.key === ' ') {
        choose()
        return
      }
      const available = enabled().map(({ index }) => index)
      const position = available.indexOf(active)
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? available.length - 1 :
        (position + (event.key === 'ArrowUp' ? -1 : 1) + available.length) % available.length
      activate(available[next], true)
    } else if (open && event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault()
      const now = Date.now()
      prefix = (now - typedAt < 700 ? prefix : '') + event.key.toLocaleLowerCase()
      typedAt = now
      const available = enabled()
      const match = available.find(({ option }) => option.label.toLocaleLowerCase().startsWith(prefix))
      if (match) activate(match.index, true)
    }
  }

  function optionAt(event: Event): number | null {
    const target = event.target
    if (!(target instanceof HTMLElement) || !target.hasAttribute('data-option-index')) return null
    const index = Number(target.dataset.optionIndex)
    return enabled().some((item) => item.index === index) ? index : null
  }

  menu.addEventListener('pointerdown', (event) => {
    if (event.target instanceof HTMLElement && event.target.hasAttribute('data-option-index')) {
      event.preventDefault()
    }
  })
  menu.addEventListener('pointermove', (event) => {
    const index = optionAt(event)
    if (index !== null) activate(index)
  })
  menu.addEventListener('click', (event) => {
    const index = optionAt(event)
    if (index !== null) {
      activate(index)
      choose()
    }
  })
  select.setAttribute('aria-expanded', 'false')
  select.addEventListener('pointerdown', pointerDown)
  select.addEventListener('mousedown', preventNative)
  select.addEventListener('click', click)
  select.addEventListener('keydown', keydown)
  select.addEventListener('blur', close)
  select.addEventListener('change', close)
  return {
    refresh,
    dispose() {
      close()
      select.removeEventListener('pointerdown', pointerDown)
      select.removeEventListener('mousedown', preventNative)
      select.removeEventListener('click', click)
      select.removeEventListener('keydown', keydown)
      select.removeEventListener('blur', close)
      select.removeEventListener('change', close)
    }
  }
}

export const vSelectMenu: Directive<HTMLSelectElement> = {
  mounted(select) { menus.set(select, attach(select)) },
  updated(select) { menus.get(select)?.refresh() },
  beforeUnmount(select) {
    menus.get(select)?.dispose()
    menus.delete(select)
  }
}
