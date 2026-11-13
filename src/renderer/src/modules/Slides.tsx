import type Konva from 'konva'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import type { FileFilter } from '../../../shared/api'
import { ModuleFrame, ToolButton } from '../components/Frame'
import { Icon } from '../components/Icon'
import { MenuButton } from '../components/Menu'
import { baseName, FILTERS, samePath, withExt } from '../lib/files'
import { call, useServices } from '../lib/services'
import { Inspector, type Align } from './slides/Inspector'
import {
  adopt,
  applyTheme,
  box,
  cloneElement,
  cloneSlide,
  contentSlide,
  newDeck,
  newId,
  SIZES,
  THEMES,
  type Deck,
  type El,
  type ShapeKind,
  type Slide,
  type Theme
} from './slides/model'
import { SlideShow } from './slides/SlideShow'
import { SlideStage, type Patch } from './slides/SlideStage'
import { SlideView } from './slides/SlideView'
import './slides/slides.css'

const OPEN_FILTERS: FileFilter[] = [{ name: 'Presentations', extensions: ['pptx', 'odp'] }]
const SAVE_FILTERS: FileFilter[] = [
  { name: 'PowerPoint presentation', extensions: ['pptx'] },
  { name: 'OpenDocument presentation', extensions: ['odp'] }
]
const THUMB_WIDTH = 168
const EXPORT_WIDTH = 1920

interface DeckFile {
  path: string | null
  /** Opened from a file this app did not write: saving over it would drop what was not imported. */
  foreign: boolean
  notes: string[]
}

const SHAPES: { kind: ShapeKind; label: string }[] = [
  { kind: 'rect', label: 'Rectangle' },
  { kind: 'roundRect', label: 'Rounded rectangle' },
  { kind: 'ellipse', label: 'Ellipse' },
  { kind: 'triangle', label: 'Triangle' },
  { kind: 'line', label: 'Line' },
  { kind: 'arrow', label: 'Arrow' }
]

export function Slides(): ReactNode {
  const { run, notify } = useServices()
  const root = useRef<HTMLDivElement>(null)
  const thumbs = useRef(new Map<string, Konva.Stage>())
  const history = useRef<{ past: Deck[]; future: Deck[] }>({ past: [], future: [] })
  const clipboard = useRef<El[]>([])
  const [file, setFile] = useState<DeckFile | null>(null)
  const [deck, setDeck] = useState<Deck | null>(null)
  const [theme, setTheme] = useState<Theme>(THEMES[0])
  const [active, setActive] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [dirty, setDirty] = useState(false)
  const [showing, setShowing] = useState(false)
  const [, bump] = useState(0)

  const slide = deck ? deck.slides[Math.min(active, deck.slides.length - 1)] : null
  const selection = slide ? slide.elements.filter((e) => selected.includes(e.id)) : []
  const ratio: '16:9' | '4:3' = deck && deck.width / deck.height < 1.5 ? '4:3' : '16:9'

  /** Replace the deck, remembering the previous one for undo. */
  const change = useCallback((next: (d: Deck) => Deck) => {
    setDeck((d) => {
      if (!d) return d
      history.current.past.push(d)
      if (history.current.past.length > 100) history.current.past.shift()
      history.current.future = []
      return next(d)
    })
    setDirty(true)
  }, [])

  const editSlide = useCallback(
    (fn: (s: Slide) => Slide) => change((d) => ({ ...d, slides: d.slides.map((s, i) => (i === Math.min(active, d.slides.length - 1) ? fn(s) : s)) })),
    [change, active]
  )

  const editSelection = useCallback(
    (fn: (el: El) => El) => editSlide((s) => ({ ...s, elements: s.elements.map((el) => (selected.includes(el.id) ? fn(el) : el)) })),
    [editSlide, selected]
  )

  const undo = useCallback(() => {
    const prev = history.current.past.pop()
    if (!prev) return
    setDeck((d) => {
      if (d) history.current.future.push(d)
      return prev
    })
    setSelected([])
    setDirty(true)
  }, [])

  const redo = useCallback(() => {
    const next = history.current.future.pop()
    if (!next) return
    setDeck((d) => {
      if (d) history.current.past.push(d)
      return next
    })
    setSelected([])
    setDirty(true)
  }, [])

  function show(next: Deck, info: DeckFile): void {
    history.current = { past: [], future: [] }
    thumbs.current.clear()
    setDeck(next)
    setFile(info)
    setActive(0)
    setSelected([])
    setDirty(false)
  }

  function create(t: Theme): void {
    setTheme(t)
    show(newDeck(t), { path: null, foreign: false, notes: [] })
  }

  async function open(): Promise<void> {
    const [path] = await window.suite.openFiles({ title: 'Open presentation', filters: OPEN_FILTERS })
    if (!path) return
    const result = await run<{ deck: Parameters<typeof adopt>[0]; notes: string[] }>(`Open ${baseName(path)}`, 'slides.open', { input: path })
    if (result) show(adopt(result.deck), { path, foreign: true, notes: result.notes })
  }

  async function saveAs(): Promise<void> {
    if (!deck || !file) return
    const output = await window.suite.saveFile({
      title: 'Save presentation as',
      defaultPath: file.path ? withExt(file.path, 'pptx', file.foreign ? '-edited' : '') : 'Presentation.pptx',
      filters: SAVE_FILTERS
    })
    if (!output) return
    if (file.foreign && file.path && samePath(file.path, output)) {
      return notify('Save presentation', 'Choose a new name so the original file, and anything in it this editor did not import, is kept.', 'error')
    }
    const saved = await run(`Save ${baseName(output)}`, 'slides.save', { output, deck })
    // .pptx stores everything in the deck; .odp is an export that drops rotation, transitions and bullets.
    if (saved && /\.pptx$/i.test(output)) {
      setFile({ path: output, foreign: false, notes: [] })
      setDirty(false)
    }
  }

  /** Every slide as a PNG data URL, rendered from the filmstrip's stages at export resolution. */
  function renderAll(): string[] | null {
    if (!deck) return null
    const images: string[] = []
    for (const s of deck.slides) {
      const stage = thumbs.current.get(s.id)
      if (!stage) return null
      images.push(stage.toDataURL({ pixelRatio: EXPORT_WIDTH / stage.width() }))
    }
    return images
  }

  async function exportPdf(): Promise<void> {
    const images = renderAll()
    if (!deck || !images) return notify('Export PDF', 'The slides are still rendering; try again in a moment.', 'error')
    const output = await window.suite.saveFile({
      title: 'Export PDF as',
      defaultPath: file?.path ? withExt(file.path, 'pdf') : 'Presentation.pdf',
      filters: FILTERS.pdf
    })
    if (output) await run(`${baseName(output)} (${images.length} slides)`, 'slides.export_pdf', { output, images, width: deck.width, height: deck.height })
  }

  async function exportImages(): Promise<void> {
    const images = renderAll()
    if (!images) return notify('Export images', 'The slides are still rendering; try again in a moment.', 'error')
    const output_dir = await window.suite.openFolder({ title: 'Choose a folder for the slide images' })
    if (!output_dir) return
    const base_name = file?.path ? baseName(file.path).replace(/\.[^.]+$/, '') : 'slide'
    await run(`Export ${images.length} slide image${images.length === 1 ? '' : 's'}`, 'slides.export_images', { output_dir, images, base_name })
  }

  // ---- adding things
  function add(el: El): void {
    editSlide((s) => ({ ...s, elements: [...s.elements, el] }))
    setSelected([el.id])
  }

  function addText(): void {
    if (!deck) return
    add({
      id: newId(), type: 'text', x: deck.width / 2 - 180, y: deck.height / 2 - 30, w: 360, h: 60, rotation: 0,
      text: 'Double-click to edit', fontFamily: theme.bodyFont, fontSize: 24, bold: false, italic: false, underline: false,
      color: theme.body, align: 'left', bullets: false
    })
  }

  function addShape(kind: ShapeKind): void {
    if (!deck) return
    const line = kind === 'line' || kind === 'arrow'
    add({
      id: newId(), type: 'shape', shape: kind, rotation: 0,
      x: deck.width / 2 - 90, y: deck.height / 2 - (line ? 0 : 60), w: 180, h: line ? 0 : 120,
      fill: line ? null : theme.accent, stroke: line ? theme.title : null, strokeWidth: line ? 3 : 0, opacity: 1
    })
  }

  async function addImage(): Promise<void> {
    if (!deck) return
    const [path] = await window.suite.openFiles({ title: 'Insert image', filters: FILTERS.images })
    if (!path) return
    try {
      const img = await call<{ data_url: string; width: number; height: number }>('slides.image_data_url', { input: path })
      const w = Math.min(img.width, deck.width * 0.5)
      const h = (w * img.height) / img.width
      add({ id: newId(), type: 'image', src: img.data_url, x: (deck.width - w) / 2, y: (deck.height - h) / 2, w, h, rotation: 0 })
    } catch (err) {
      notify('Insert image', err instanceof Error ? err.message : String(err), 'error')
    }
  }

  // ---- slides
  function addSlide(): void {
    if (!deck) return
    const at = active + 1
    change((d) => ({ ...d, slides: [...d.slides.slice(0, at), contentSlide(theme, d.width, d.height), ...d.slides.slice(at)] }))
    setActive(at)
    setSelected([])
  }

  function duplicateSlide(): void {
    if (!slide) return
    const at = active + 1
    change((d) => ({ ...d, slides: [...d.slides.slice(0, at), cloneSlide(slide), ...d.slides.slice(at)] }))
    setActive(at)
    setSelected([])
  }

  function deleteSlide(): void {
    if (!deck || deck.slides.length <= 1) return
    change((d) => ({ ...d, slides: d.slides.filter((_, i) => i !== active) }))
    setActive(Math.max(0, active - 1))
    setSelected([])
  }

  function moveSlide(from: number, to: number): void {
    if (!deck || to < 0 || to >= deck.slides.length || from === to) return
    change((d) => {
      const slides = [...d.slides]
      slides.splice(to, 0, ...slides.splice(from, 1))
      return { ...d, slides }
    })
    setActive(to)
  }

  // ---- selection operations
  const removeSelection = useCallback(() => {
    if (selected.length === 0) return
    editSlide((s) => ({ ...s, elements: s.elements.filter((el) => !selected.includes(el.id)) }))
    setSelected([])
  }, [editSlide, selected])

  const paste = useCallback(
    (items: El[]) => {
      if (items.length === 0) return
      const copies = items.map((el) => cloneElement(el))
      editSlide((s) => ({ ...s, elements: [...s.elements, ...copies] }))
      setSelected(copies.map((c) => c.id))
    },
    [editSlide]
  )

  function align(how: Align): void {
    if (!deck || selection.length === 0) return
    // One element aligns to the slide; several align to their common bounding box.
    const boxes = selection.map(box)
    const frame =
      selection.length === 1
        ? { left: 0, top: 0, right: deck.width, bottom: deck.height }
        : {
            left: Math.min(...boxes.map((b) => b.left)),
            top: Math.min(...boxes.map((b) => b.top)),
            right: Math.max(...boxes.map((b) => b.right)),
            bottom: Math.max(...boxes.map((b) => b.bottom))
          }
    editSelection((el) => {
      const b = box(el)
      const dx =
        how === 'left' ? frame.left - b.left : how === 'right' ? frame.right - b.right : how === 'center' ? (frame.left + frame.right) / 2 - (b.left + b.right) / 2 : 0
      const dy =
        how === 'top' ? frame.top - b.top : how === 'bottom' ? frame.bottom - b.bottom : how === 'middle' ? (frame.top + frame.bottom) / 2 - (b.top + b.bottom) / 2 : 0
      return { ...el, x: el.x + dx, y: el.y + dy }
    })
  }

  function order(direction: 'front' | 'back'): void {
    editSlide((s) => {
      const picked = s.elements.filter((el) => selected.includes(el.id))
      const rest = s.elements.filter((el) => !selected.includes(el.id))
      return { ...s, elements: direction === 'front' ? [...rest, ...picked] : [...picked, ...rest] }
    })
  }

  function setRatio(next: '16:9' | '4:3'): void {
    const [width, height] = SIZES[next]
    // Scale positions horizontally so content keeps its place relative to the slide edges.
    change((d) => {
      const k = width / d.width
      return {
        ...d,
        width,
        height,
        slides: d.slides.map((s) => ({ ...s, elements: s.elements.map((el) => ({ ...el, x: el.x * k, w: el.w * k })) }))
      }
    })
  }

  // Keyboard shortcuts, only while this workspace is visible and focus is not in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (!deck || showing || !root.current || root.current.offsetParent === null) return
      const target = e.target as HTMLElement
      if (target.closest('input, textarea, select, [contenteditable="true"], .dialog')) return
      const mod = e.ctrlKey || e.metaKey
      const key = e.key.toLowerCase()
      const step = e.shiftKey ? 10 : 1
      const nudge: Record<string, [number, number]> = { arrowleft: [-step, 0], arrowright: [step, 0], arrowup: [0, -step], arrowdown: [0, step] }
      if (mod && key === 'z') (e.shiftKey ? redo : undo)()
      else if (mod && key === 'y') redo()
      else if (mod && key === 'c') clipboard.current = selection
      else if (mod && key === 'v') paste(clipboard.current)
      else if (mod && key === 'd') paste(selection)
      else if ((key === 'delete' || key === 'backspace') && selected.length) removeSelection()
      else if (nudge[key] && selected.length) editSelection((el) => ({ ...el, x: el.x + nudge[key][0], y: el.y + nudge[key][1] }))
      else if (key === 'escape') setSelected([])
      else if (key === 'f5') setShowing(true)
      else return
      e.preventDefault()
      bump((n) => n + 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [deck, showing, selection, selected, undo, redo, paste, removeSelection, editSelection])

  const notes = file?.notes ?? []

  return (
    <div className="sl-root" ref={root}>
      <ModuleFrame
        title="Slides"
        file={file ? (file.path ?? 'Untitled presentation') : null}
        dirty={dirty}
        notice={notes.length > 0 && `Not imported from the original, and so not in a saved copy: ${notes.join(' · ')}`}
        toolbar={
          <>
            <MenuButton icon="plus" label="New" items={THEMES.map((t) => ({ label: `${t.name} theme`, onSelect: () => create(t) }))} />
            <ToolButton icon="open" label="Open" primary={!deck} onClick={() => void open()} />
            <ToolButton icon="save" label="Save as…" primary={!!deck && dirty} disabled={!deck} onClick={() => void saveAs()} />
            <span className="sep" />
            <ToolButton icon="type" label="Text" disabled={!deck} onClick={addText} />
            <MenuButton icon="square" label="Shape" disabled={!deck} items={SHAPES.map((s) => ({ label: s.label, onSelect: () => addShape(s.kind) }))} />
            <ToolButton icon="image" label="Image" disabled={!deck} onClick={() => void addImage()} />
            <span className="sep" />
            <ToolButton icon="undo" label="Undo" disabled={history.current.past.length === 0} onClick={undo} />
            <ToolButton icon="redo" label="Redo" disabled={history.current.future.length === 0} onClick={redo} />
            <span className="sep" />
            <ToolButton icon="play" label="Present" disabled={!deck} onClick={() => setShowing(true)} />
            <MenuButton
              icon="layers"
              label="Export"
              disabled={!deck}
              items={[
                { icon: 'pdf', label: 'PDF (one slide per page)', onSelect: () => void exportPdf() },
                { icon: 'image', label: 'Images (PNG per slide)', onSelect: () => void exportImages() }
              ]}
            />
          </>
        }
      >
        {!deck || !slide ? (
          <div className="sl-gallery">
            <h2>Start a presentation</h2>
            <p className="muted">Choose a theme, or open a .pptx or .odp file.</p>
            <div className="sl-themes">
              {THEMES.map((t) => (
                <button key={t.id} className="sl-theme" onClick={() => create(t)}>
                  <span className="sl-theme-card" style={{ background: t.background }}>
                    <i style={{ background: t.accent }} />
                    <b style={{ color: t.title, fontFamily: t.headFont }}>Title</b>
                    <small style={{ color: t.body, fontFamily: t.bodyFont }}>Body text</small>
                  </span>
                  <strong>{t.name}</strong>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="sl-layout">
            <div className="sl-strip" aria-label="Slides">
              {deck.slides.map((s, i) => (
                <div
                  key={s.id}
                  className={`sl-thumb${i === active ? ' selected' : ''}`}
                  draggable
                  onDragStart={(e) => e.dataTransfer.setData('text/plain', String(i))}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault()
                    const from = Number(e.dataTransfer.getData('text/plain'))
                    if (Number.isInteger(from)) moveSlide(from, i)
                  }}
                >
                  <span className="sl-thumb-num">{i + 1}</span>
                  <button
                    className="sl-thumb-face"
                    aria-label={`Slide ${i + 1}`}
                    aria-pressed={i === active}
                    onClick={() => {
                      setActive(i)
                      setSelected([])
                    }}
                  >
                    <SlideView
                      ref={(stage) => {
                        if (stage) thumbs.current.set(s.id, stage)
                        else thumbs.current.delete(s.id)
                      }}
                      slide={s}
                      width={deck.width}
                      height={deck.height}
                      scale={THUMB_WIDTH / deck.width}
                    />
                    {s.transition.type !== 'none' && <span className="sl-thumb-tr" title={`Transition: ${s.transition.type}`} />}
                  </button>
                </div>
              ))}
              <div className="sl-strip-actions">
                <button className="btn" onClick={addSlide}>
                  <Icon name="plus" size={15} /> Slide
                </button>
                <button className="btn" title="Duplicate slide" aria-label="Duplicate slide" onClick={duplicateSlide}>
                  <Icon name="copy" size={15} />
                </button>
                <button className="btn" title="Move slide up" aria-label="Move slide up" disabled={active === 0} onClick={() => moveSlide(active, active - 1)}>
                  <Icon name="up" size={15} />
                </button>
                <button className="btn" title="Move slide down" aria-label="Move slide down" disabled={active >= deck.slides.length - 1} onClick={() => moveSlide(active, active + 1)}>
                  <Icon name="down" size={15} />
                </button>
                <button className="btn" title="Delete slide" aria-label="Delete slide" disabled={deck.slides.length <= 1} onClick={deleteSlide}>
                  <Icon name="trash" size={15} />
                </button>
              </div>
            </div>

            <div className="sl-center">
              <SlideStage
                slide={slide}
                width={deck.width}
                height={deck.height}
                selected={selected}
                onSelect={setSelected}
                onPatch={(patches: Patch[]) =>
                  editSlide((s) => ({
                    ...s,
                    elements: s.elements.map((el) => {
                      const patch = patches.find((p) => p.id === el.id)
                      return patch ? ({ ...el, ...patch } as El) : el
                    })
                  }))
                }
                onText={(id, text) => {
                  const el = slide.elements.find((e) => e.id === id)
                  if (el?.type === 'text' && el.text !== text) {
                    editSlide((s) => ({ ...s, elements: s.elements.map((e) => (e.id === id && e.type === 'text' ? { ...e, text } : e)) }))
                  }
                }}
              />
              <label className="sl-notes">
                <span>Speaker notes</span>
                <textarea
                  value={slide.notes}
                  placeholder="Notes for this slide"
                  onChange={(e) => {
                    const notesText = e.target.value
                    editSlide((s) => ({ ...s, notes: notesText }))
                  }}
                />
              </label>
            </div>

            <Inspector
              slide={slide}
              selection={selection}
              ratio={ratio}
              onElement={(patch) => editSelection((el) => ({ ...el, ...patch }) as El)}
              onSlide={(patch) => editSlide((s) => ({ ...s, ...patch }))}
              onTheme={(id) => {
                const next = THEMES.find((t) => t.id === id)
                if (!next) return
                setTheme(next)
                change((d) => applyTheme(d, next))
              }}
              onRatio={setRatio}
              onAlign={align}
              onOrder={order}
              onDuplicate={() => paste(selection)}
              onDelete={removeSelection}
            />
          </div>
        )}
      </ModuleFrame>
      {showing && deck && <SlideShow deck={deck} start={active} onClose={() => setShowing(false)} />}
    </div>
  )
}
