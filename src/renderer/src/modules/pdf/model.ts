// The PDF editing model. All coordinates are PDF points with a top-left origin
// on the page as displayed; `page` is the index in the ORIGINAL file, so an
// edit follows its page when pages are reordered. This is exactly the shape
// the engine's `pdf.apply_edits` accepts.

export type Tool = 'select' | 'edittext' | 'text' | 'highlight' | 'ink' | 'rect' | 'ellipse' | 'line' | 'arrow' | 'note' | 'redact'

interface Base {
  id: string
  page: number
}

export interface Box {
  x: number
  y: number
  w: number
  h: number
}

export type FontFamily = 'sans' | 'serif' | 'mono'

export interface TextEdit extends Base {
  type: 'text'
  x: number
  y: number
  text: string
  size: number
  color: string
  bold?: boolean
  italic?: boolean
  family?: FontFamily
  /** Set when this edit changes text that was already in the PDF: the box of the original line, which is removed on save. */
  replaces?: Box
}

/** A run of existing text on a page, as reported by the engine's pdf.text_lines. */
export interface TextLine extends Box {
  text: string
  size: number
  family: FontFamily
  bold: boolean
  italic: boolean
  color: string
}

export const FONT_CSS: Record<FontFamily, string> = {
  sans: 'Arial, Helvetica, sans-serif',
  serif: "'Times New Roman', Times, serif",
  mono: "'Courier New', Courier, monospace"
}

export interface BoxEdit extends Base {
  type: 'highlight' | 'rect' | 'ellipse' | 'redact'
  x: number
  y: number
  w: number
  h: number
  color: string
  width: number
}

export interface LineEdit extends Base {
  type: 'line' | 'arrow'
  x1: number
  y1: number
  x2: number
  y2: number
  color: string
  width: number
}

export interface InkEdit extends Base {
  type: 'ink'
  points: [number, number][]
  color: string
  width: number
}

export interface ImageEdit extends Base {
  type: 'image'
  x: number
  y: number
  w: number
  h: number
  data_url: string
}

export interface NoteEdit extends Base {
  type: 'note'
  x: number
  y: number
  text: string
}

export type Edit = TextEdit | BoxEdit | LineEdit | InkEdit | ImageEdit | NoteEdit

export interface PageSpec {
  /** Stable React key; a page keeps it while it moves. */
  key: string
  source: number
  rotate: number
}

export interface Style {
  color: string
  width: number
  size: number
}

export const COLORS = ['#111827', '#d92d20', '#f79009', '#ffe600', '#12b76a', '#2e6fdb', '#7a5af8']

let seq = 0
export const newId = (): string => `e${++seq}`

export const TEXT_LINE = 1.2

/** Rough text extent; exact metrics are not needed for a selection outline. */
function textBox(e: TextEdit): Box {
  const lines = e.text.split('\n')
  const longest = Math.max(1, ...lines.map((l) => l.length))
  return { x: e.x, y: e.y, w: longest * e.size * 0.52, h: lines.length * e.size * TEXT_LINE }
}

export function bounds(e: Edit): Box {
  switch (e.type) {
    case 'text':
      return textBox(e)
    case 'note':
      return { x: e.x, y: e.y, w: 20, h: 20 }
    case 'line':
    case 'arrow':
      return { x: Math.min(e.x1, e.x2), y: Math.min(e.y1, e.y2), w: Math.abs(e.x2 - e.x1), h: Math.abs(e.y2 - e.y1) }
    case 'ink': {
      const xs = e.points.map((p) => p[0])
      const ys = e.points.map((p) => p[1])
      const x = Math.min(...xs)
      const y = Math.min(...ys)
      return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y }
    }
    default:
      return { x: e.x, y: e.y, w: e.w, h: e.h }
  }
}

export function moved<T extends Edit>(e: T, dx: number, dy: number): T {
  switch (e.type) {
    case 'line':
    case 'arrow':
      return { ...e, x1: e.x1 + dx, y1: e.y1 + dy, x2: e.x2 + dx, y2: e.y2 + dy }
    case 'ink':
      return { ...e, points: e.points.map(([x, y]) => [x + dx, y + dy] as [number, number]) }
    default:
      return { ...e, x: e.x + dx, y: e.y + dy }
  }
}

export const isResizable = (e: Edit): e is BoxEdit | ImageEdit =>
  e.type === 'highlight' || e.type === 'rect' || e.type === 'ellipse' || e.type === 'redact' || e.type === 'image'

/** What the engine needs: the edit without UI-only fields. */
export function toEngine(e: Edit): Record<string, unknown> {
  const { id: _id, ...rest } = e
  return rest
}
