// The deck model. Lengths are points (a 16:9 slide is 960 x 540); this is the
// shape the engine's slides.open / slides.save exchange.

export type Role = 'title' | 'body' | 'accent'

interface Base {
  id: string
  x: number
  y: number
  w: number
  h: number
  rotation: number
  /** Which theme colour/font this element follows when the theme changes. Not stored in .pptx. */
  role?: Role
}

export interface TextEl extends Base {
  type: 'text'
  text: string
  fontFamily: string
  fontSize: number
  bold: boolean
  italic: boolean
  underline: boolean
  color: string
  align: 'left' | 'center' | 'right'
  bullets: boolean
}

export type ShapeKind = 'rect' | 'roundRect' | 'ellipse' | 'triangle' | 'line' | 'arrow'

export interface ShapeEl extends Base {
  type: 'shape'
  shape: ShapeKind
  fill: string | null
  stroke: string | null
  strokeWidth: number
  opacity: number
}

export interface ImageEl extends Base {
  type: 'image'
  src: string
}

export type El = TextEl | ShapeEl | ImageEl

export type TransitionType = 'none' | 'fade' | 'push' | 'wipe' | 'split' | 'cover'

export interface Slide {
  id: string
  background: string
  notes: string
  transition: { type: TransitionType; duration: number }
  elements: El[]
}

export interface Deck {
  width: number
  height: number
  slides: Slide[]
}

export interface Theme {
  id: string
  name: string
  background: string
  title: string
  body: string
  accent: string
  headFont: string
  bodyFont: string
}

export const THEMES: Theme[] = [
  { id: 'clean', name: 'Clean', background: '#ffffff', title: '#101828', body: '#344054', accent: '#2e6fdb', headFont: 'Segoe UI', bodyFont: 'Segoe UI' },
  { id: 'midnight', name: 'Midnight', background: '#0b1f33', title: '#ffffff', body: '#c9d6e4', accent: '#f0b429', headFont: 'Georgia', bodyFont: 'Calibri' },
  { id: 'forest', name: 'Forest', background: '#f3f7f2', title: '#1b4332', body: '#2d6a4f', accent: '#40916c', headFont: 'Cambria', bodyFont: 'Calibri' },
  { id: 'sunset', name: 'Sunset', background: '#fff4ea', title: '#7a2e0e', body: '#93370d', accent: '#f79009', headFont: 'Georgia', bodyFont: 'Verdana' },
  { id: 'slate', name: 'Slate', background: '#1f2933', title: '#f5f7fa', body: '#cbd2d9', accent: '#47c1bf', headFont: 'Arial', bodyFont: 'Arial' },
  { id: 'berry', name: 'Berry', background: '#fdf2f8', title: '#701a75', body: '#86198f', accent: '#db2777', headFont: 'Times New Roman', bodyFont: 'Tahoma' }
]

export const FONTS = ['Arial', 'Calibri', 'Cambria', 'Courier New', 'Georgia', 'Segoe UI', 'Tahoma', 'Times New Roman', 'Verdana']
export const TRANSITIONS: TransitionType[] = ['none', 'fade', 'push', 'wipe', 'split', 'cover']
export const SIZES = { '16:9': [960, 540], '4:3': [720, 540] } as const

let seq = 0
export const newId = (prefix = 'el'): string => `${prefix}${++seq}`

export const isLine = (el: El): boolean => el.type === 'shape' && (el.shape === 'line' || el.shape === 'arrow')

function text(theme: Theme, role: 'title' | 'body', box: Pick<Base, 'x' | 'y' | 'w' | 'h'>, value: string, fontSize: number, extra: Partial<TextEl> = {}): TextEl {
  return {
    id: newId(),
    type: 'text',
    rotation: 0,
    role,
    text: value,
    fontFamily: role === 'title' ? theme.headFont : theme.bodyFont,
    fontSize,
    bold: role === 'title',
    italic: false,
    underline: false,
    color: role === 'title' ? theme.title : theme.body,
    align: 'left',
    bullets: false,
    ...box,
    ...extra
  }
}

function accent(theme: Theme, box: Pick<Base, 'x' | 'y' | 'w' | 'h'>): ShapeEl {
  return { id: newId(), type: 'shape', shape: 'rect', rotation: 0, role: 'accent', fill: theme.accent, stroke: null, strokeWidth: 0, opacity: 1, ...box }
}

const blank = (theme: Theme, elements: El[]): Slide => ({
  id: newId('slide'),
  background: theme.background,
  notes: '',
  transition: { type: 'none', duration: 0.6 },
  elements
})

export function titleSlide(theme: Theme, W: number, H: number): Slide {
  return blank(theme, [
    accent(theme, { x: 0, y: 0, w: 22, h: H }),
    text(theme, 'title', { x: 80, y: H * 0.3, w: W - 160, h: 110 }, 'Presentation title', 44),
    text(theme, 'body', { x: 80, y: H * 0.3 + 120, w: W - 160, h: 50 }, 'Subtitle or presenter name', 22)
  ])
}

export function contentSlide(theme: Theme, W: number, H: number): Slide {
  return blank(theme, [
    text(theme, 'title', { x: 60, y: 36, w: W - 120, h: 56 }, 'Slide title', 32),
    accent(theme, { x: 60, y: 98, w: 84, h: 4 }),
    text(theme, 'body', { x: 60, y: 124, w: W - 120, h: H - 180 }, 'First point\nSecond point\nThird point', 22, { bullets: true })
  ])
}

export function newDeck(theme: Theme, ratio: keyof typeof SIZES = '16:9'): Deck {
  const [width, height] = SIZES[ratio]
  return { width, height, slides: [titleSlide(theme, width, height)] }
}

/** Recolour slide backgrounds and every element that still follows a theme role. */
export function applyTheme(deck: Deck, theme: Theme): Deck {
  return {
    ...deck,
    slides: deck.slides.map((slide) => ({
      ...slide,
      background: theme.background,
      elements: slide.elements.map((el): El => {
        if (el.type === 'text' && el.role === 'title') return { ...el, color: theme.title, fontFamily: theme.headFont }
        if (el.type === 'text' && el.role === 'body') return { ...el, color: theme.body, fontFamily: theme.bodyFont }
        if (el.type === 'shape' && el.role === 'accent') return { ...el, fill: theme.accent }
        return el
      })
    }))
  }
}

/** Give imported slides and elements the ids the editor needs. */
export function adopt(deck: { width: number; height: number; slides: (Omit<Slide, 'id' | 'elements'> & { elements: Omit<El, 'id'>[] })[] }): Deck {
  return {
    width: deck.width,
    height: deck.height,
    slides: deck.slides.map((s) => ({ ...s, id: newId('slide'), elements: s.elements.map((e) => ({ ...e, id: newId() }) as El) }))
  }
}

export function cloneElement(el: El, dx = 16, dy = 16): El {
  return { ...el, id: newId(), x: el.x + dx, y: el.y + dy }
}

export function cloneSlide(slide: Slide): Slide {
  return { ...slide, id: newId('slide'), elements: slide.elements.map((e) => cloneElement(e, 0, 0)) }
}

/** Axis-aligned box of an element (lines may have negative w/h). */
export function box(el: El): { left: number; top: number; right: number; bottom: number } {
  return { left: Math.min(el.x, el.x + el.w), top: Math.min(el.y, el.y + el.h), right: Math.max(el.x, el.x + el.w), bottom: Math.max(el.y, el.y + el.h) }
}
