import { afterEach, describe, expect, it, vi } from 'vitest'

import { revealWithinPane } from '../src/utils/revealWithinPane'

afterEach(() => vi.restoreAllMocks())

describe('revealWithinPane', () => {
  it.each([
    { name: 'already visible target', top: 140, height: 30, expected: 353 },
    { name: 'target above', top: 80, height: 20, expected: 288 },
    { name: 'target below', top: 310, height: 30, expected: 523 }
  ])('centers a $name without scrolling its ancestors', ({ top, height, expected }) => {
    const outer = document.createElement('div')
    const pane = document.createElement('div')
    const target = document.createElement('span')
    outer.append(pane)
    pane.append(target)
    outer.scrollTop = 50
    pane.scrollTop = 400
    pane.scrollLeft = 25
    Object.defineProperties(pane, {
      clientHeight: { value: 200 },
      clientTop: { value: 2 }
    })
    vi.spyOn(pane, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 100, 300, 204))
    vi.spyOn(target, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, top, 20, height))

    revealWithinPane(target, pane, false, 'center')

    expect(pane.scrollTop).toBe(expected)
    expect(pane.scrollLeft).toBe(25)
    expect(outer.scrollTop).toBe(50)
  })

  it.each([
    { name: 'visible target', top: 140, height: 30, expected: 100 },
    { name: 'target above', top: 80, height: 20, expected: 78 },
    { name: 'target below', top: 310, height: 30, expected: 138 },
    { name: 'oversized target below', top: 140, height: 300, expected: 138 }
  ])('only adjusts the owning pane for a $name', ({ top, height, expected }) => {
    const outer = document.createElement('div')
    const pane = document.createElement('div')
    const target = document.createElement('span')
    outer.append(pane)
    pane.append(target)
    outer.scrollTop = 50
    pane.scrollTop = 100
    pane.scrollLeft = 25
    Object.defineProperties(pane, {
      clientHeight: { value: 200 },
      clientTop: { value: 2 }
    })
    vi.spyOn(pane, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 100, 300, 204))
    vi.spyOn(target, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, top, 20, height))

    revealWithinPane(target, pane)

    expect(pane.scrollTop).toBe(expected)
    expect(pane.scrollLeft).toBe(25)
    expect(outer.scrollTop).toBe(50)
  })

  it('does not change a hidden pane or fall back to scrolling the page', () => {
    const pane = document.createElement('div')
    const target = document.createElement('span')
    pane.scrollTop = 75
    pane.append(target)

    revealWithinPane(target, pane)
    revealWithinPane(target, null)

    expect(pane.scrollTop).toBe(75)
  })

})
