import type { LayoutGlyph, LayoutPage } from '../api/originalPreview'

export type LayoutRectangle = Pick<LayoutGlyph, 'x' | 'y' | 'width' | 'height'>

export function layoutRectangles(page: LayoutPage, start: number, end: number): LayoutRectangle[] {
  let low = 0
  let high = page.glyphs.length
  while (low < high) {
    const middle = Math.floor((low + high) / 2)
    if (page.glyphs[middle].end <= start) low = middle + 1
    else high = middle
  }
  if (start === end) {
    const anchor = page.glyphs[low]?.start === start
      ? page.glyphs[low] : page.glyphs[low - 1]?.end === start ? page.glyphs[low - 1] : undefined
    return anchor ? [{
      x: anchor.start === start ? anchor.x : anchor.x + anchor.width - 2,
      y: anchor.y, width: 2, height: anchor.height
    }] : []
  }
  const rectangles: LayoutRectangle[] = []
  for (let index = low; index < page.glyphs.length; index += 1) {
    const glyph = page.glyphs[index]
    if (glyph.start >= end) break
    const previous = rectangles.at(-1)
    if (previous && Math.abs(previous.y - glyph.y) < glyph.height * 0.3 &&
      glyph.x >= previous.x && glyph.x - previous.x - previous.width <= glyph.height * 0.8) {
      previous.width = Math.max(previous.width, glyph.x + glyph.width - previous.x)
      previous.height = Math.max(previous.height, glyph.y + glyph.height - previous.y)
    } else {
      rectangles.push({ x: glyph.x, y: glyph.y, width: glyph.width, height: glyph.height })
    }
  }
  return rectangles
}

export function rectangleStyle(rectangle: LayoutRectangle, page: LayoutPage): Record<string, string> {
  return {
    left: `${rectangle.x / page.width * 100}%`,
    top: `${rectangle.y / page.height * 100}%`,
    width: `${rectangle.width / page.width * 100}%`,
    height: `${rectangle.height / page.height * 100}%`
  }
}
