import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { call } from '../../lib/services'
import { bounds, FONT_CSS, isResizable, moved, newId, TEXT_LINE, type Box, type Edit, type FontFamily, type Style, type TextEdit, type TextLine, type Tool } from './model'

interface Props {
  path: string
  password?: string
  /** Index in the original file. */
  source: number
  /** Displayed page size in points. */
  size: [number, number]
  rotate: number
  zoom: number
  edits: Edit[]
  /** Existing text on this page that can be clicked to change it (only while the Edit text tool is active). */
  lines: TextLine[]
  tool: Tool
  style: Style
  selected: string | null
  onSelect(id: string | null): void
  onAdd(edit: Edit): void
  onChange(edit: Edit): void
  onRemove(id: string): void
  /** Ask for the text of a sticky note placed at (x, y). */
  onNote(x: number, y: number): void
}

type Drag =
  | { kind: 'draw'; edit: Edit }
  | { kind: 'move'; origin: Edit; fromX: number; fromY: number; edit: Edit }
  | { kind: 'resize'; edit: Edit }

interface Typing {
  /** Existing edit being re-typed, or null for a new one. */
  id: string | null
  x: number
  y: number
  text: string
  size: number
  color: string
  bold?: boolean
  italic?: boolean
  family?: FontFamily
  /** Editing text that is already in the PDF: its box, and what it said. */
  replaces?: Box
  original?: string
}

const MIN_DRAW = 3

export function PageCanvas(props: Props): ReactNode {
  const { size, rotate, tool, style, edits, source } = props
  const [W, H] = size
  const stage = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [avail, setAvail] = useState(800)
  const [image, setImage] = useState<{ key: string; src?: string; error?: string }>({ key: '' })
  const [drag, setDrag] = useState<Drag | null>(null)
  const [typing, setTyping] = useState<Typing | null>(null)
  const key = `${props.path}:${source}`

  useLayoutEffect(() => {
    const el = stage.current
    if (!el) return
    const measure = (): void => {
      // Hidden workspaces report 0; keep the last real width.
      if (el.clientWidth > 0) setAvail(el.clientWidth - 48)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let cancelled = false
    call<{ data_url: string }>('pdf.render_page', { input: props.path, page: source, width: 1400, password: props.password })
      .then((r) => !cancelled && setImage({ key, src: r.data_url }))
      .catch((err: Error) => !cancelled && setImage({ key, error: err.message }))
    return () => {
      cancelled = true
    }
  }, [props.path, source, props.password, key])

  useEffect(() => setTyping(null), [key])

  // Fit the page as displayed (after rotation) to the stage width, then apply zoom.
  const quarter = rotate % 180 !== 0
  const shownW = quarter ? H : W
  const scale = Math.min(avail / shownW, 1.7) * props.zoom
  const boxW = W * scale
  const boxH = H * scale
  const outerW = quarter ? boxH : boxW
  const outerH = quarter ? boxW : boxH

  /** Pointer position in page points; the SVG's own matrix accounts for zoom and rotation. */
  function point(e: { clientX: number; clientY: number }): [number, number] {
    const matrix = svg.current?.getScreenCTM()
    if (!matrix) return [0, 0]
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(matrix.inverse())
    return [Math.min(Math.max(p.x, 0), W), Math.min(Math.max(p.y, 0), H)]
  }

  function commitTyping(): void {
    if (!typing) return
    const text = typing.text.replace(/\s+$/, '')
    if (typing.id) {
      const existing = edits.find((e) => e.id === typing.id)
      if (existing && existing.type === 'text') {
        // An emptied replacement means "delete the original line", so it is kept.
        if (text === '' && !existing.replaces) props.onRemove(existing.id)
        else if (text !== existing.text) props.onChange({ ...existing, text })
      }
    } else if (typing.replaces ? text !== typing.original : text !== '') {
      props.onAdd({
        id: newId(),
        page: source,
        type: 'text',
        x: typing.x,
        y: typing.y,
        text,
        size: typing.size,
        color: typing.color,
        bold: typing.bold,
        italic: typing.italic,
        family: typing.family,
        replaces: typing.replaces
      })
    }
    setTyping(null)
  }

  function onPointerDown(e: ReactPointerEvent<SVGSVGElement>): void {
    if (e.button !== 0) return
    if (typing) commitTyping()
    const [x, y] = point(e)
    const target = e.target as SVGElement

    if (tool === 'edittext') {
      const index = target.getAttribute('data-line')
      const line = index === null ? undefined : props.lines[Number(index)]
      if (line) {
        setTyping({
          id: null,
          x: line.x,
          y: line.y,
          text: line.text,
          original: line.text,
          size: line.size,
          color: line.color,
          bold: line.bold,
          italic: line.italic,
          family: line.family,
          replaces: { x: line.x, y: line.y, w: line.w, h: line.h }
        })
      }
      return
    }

    if (tool === 'select') {
      const id = target.closest('[data-id]')?.getAttribute('data-id') ?? null
      const edit = edits.find((it) => it.id === id) ?? null
      props.onSelect(edit?.id ?? null)
      if (!edit) return
      e.currentTarget.setPointerCapture(e.pointerId)
      setDrag(target.dataset.handle ? { kind: 'resize', edit } : { kind: 'move', origin: edit, fromX: x, fromY: y, edit })
      return
    }

    props.onSelect(null)
    if (tool === 'text') {
      setTyping({ id: null, x, y, text: '', size: style.size, color: style.color })
      return
    }
    if (tool === 'note') {
      props.onNote(x, y)
      return
    }
    e.currentTarget.setPointerCapture(e.pointerId)
    const base = { id: newId(), page: source, color: style.color, width: style.width }
    if (tool === 'ink') setDrag({ kind: 'draw', edit: { ...base, type: 'ink', points: [[x, y]] } })
    else if (tool === 'line' || tool === 'arrow') setDrag({ kind: 'draw', edit: { ...base, type: tool, x1: x, y1: y, x2: x, y2: y } })
    else setDrag({ kind: 'draw', edit: { ...base, type: tool, x, y, w: 0, h: 0 } })
  }

  function onPointerMove(e: ReactPointerEvent<SVGSVGElement>): void {
    if (!drag) return
    const [x, y] = point(e)
    if (drag.kind === 'move') {
      setDrag({ ...drag, edit: moved(drag.origin, x - drag.fromX, y - drag.fromY) })
      return
    }
    const edit = drag.edit
    if (drag.kind === 'resize') {
      if (isResizable(edit)) setDrag({ kind: 'resize', edit: { ...edit, w: Math.max(6, x - edit.x), h: Math.max(6, y - edit.y) } })
      return
    }
    if (edit.type === 'ink') setDrag({ kind: 'draw', edit: { ...edit, points: [...edit.points, [x, y]] } })
    else if (edit.type === 'line' || edit.type === 'arrow') setDrag({ kind: 'draw', edit: { ...edit, x2: x, y2: y } })
    else if (isResizable(edit)) setDrag({ kind: 'draw', edit: { ...edit, w: x - edit.x, h: y - edit.y } })
  }

  function onPointerUp(): void {
    if (!drag) return
    setDrag(null)
    let edit = drag.edit
    if (drag.kind !== 'draw') {
      if (edit !== (drag.kind === 'move' ? drag.origin : null)) props.onChange(edit)
      return
    }
    // Normalise boxes dragged up/left, and drop accidental clicks.
    if (isResizable(edit)) {
      edit = { ...edit, x: Math.min(edit.x, edit.x + edit.w), y: Math.min(edit.y, edit.y + edit.h), w: Math.abs(edit.w), h: Math.abs(edit.h) }
      if (edit.w < MIN_DRAW || edit.h < MIN_DRAW) return
    } else {
      const b = bounds(edit)
      if (b.w < MIN_DRAW && b.h < MIN_DRAW) return
    }
    props.onAdd(edit)
  }

  function onDoubleClick(e: React.MouseEvent<SVGSVGElement>): void {
    const id = (e.target as SVGElement).closest('[data-id]')?.getAttribute('data-id')
    const edit = edits.find((it) => it.id === id)
    if (edit?.type === 'text') {
      setTyping({ id: edit.id, x: edit.x, y: edit.y, text: edit.text, size: edit.size, color: edit.color, bold: edit.bold, italic: edit.italic, family: edit.family, replaces: edit.replaces })
    }
  }

  // While dragging, the live copy replaces the stored edit.
  const shown = edits.filter((e) => e.id !== drag?.edit.id && e.id !== typing?.id)
  if (drag) shown.push(drag.edit)
  const active = drag?.edit ?? edits.find((e) => e.id === props.selected) ?? null
  // A line that already has a pending change is edited through that change, not offered again.
  const changed = new Set(edits.flatMap((e) => (e.type === 'text' && e.replaces ? [`${e.replaces.x}:${e.replaces.y}`] : [])))
  const current = image.key === key

  return (
    <div className="pdf-stage" ref={stage}>
      {current && image.error && <p className="error-text">{image.error}</p>}
      <div className="pdf-sheet-box" style={{ width: outerW, height: outerH }}>
        <div
          className="pdf-sheet"
          style={{ width: boxW, height: boxH, left: (outerW - boxW) / 2, top: (outerH - boxH) / 2, transform: `rotate(${rotate}deg)` }}
        >
          {image.src && <img className={current ? '' : 'stale'} src={image.src} alt={`Page ${source + 1}`} draggable={false} />}
          <svg
            ref={svg}
            className={`pdf-overlay tool-${tool}`}
            viewBox={`0 0 ${W} ${H}`}
            // Keep focus where it is: otherwise the click that opens the text editor
            // would immediately blur (and so close) it.
            onMouseDown={(e) => e.preventDefault()}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onDoubleClick={onDoubleClick}
          >
            {shown.map((e) => (
              <Shape key={e.id} edit={e} />
            ))}
            {tool === 'select' && active && !typing && <Outline edit={active} />}
            {tool === 'edittext' &&
              !typing &&
              props.lines.map((line, i) =>
                changed.has(`${line.x}:${line.y}`) ? null : (
                  <rect key={i} data-line={i} className="pdf-line" x={line.x - 1} y={line.y - 1} width={line.w + 2} height={line.h + 2} rx={1.5}>
                    <title>Click to edit this text</title>
                  </rect>
                )
              )}
          </svg>
          {typing && (
            <textarea
              className="pdf-typing"
              autoFocus
              spellCheck={false}
              value={typing.text}
              placeholder="Type here"
              style={{
                fontFamily: FONT_CSS[typing.family ?? 'sans'],
                fontWeight: typing.bold ? 700 : 400,
                fontStyle: typing.italic ? 'italic' : 'normal',
                // Editing existing text: an opaque box hides the original underneath while typing.
                background: typing.replaces ? '#fff' : undefined,
                left: typing.x * scale,
                // The engine puts the baseline 0.8 em below y; a 1.2 line-height box puts it ~1 em below its top.
                top: (typing.y - typing.size * 0.2) * scale,
                fontSize: typing.size * scale,
                lineHeight: TEXT_LINE,
                color: typing.color,
                width: Math.max(120, (W - typing.x) * scale - 4),
                minWidth: typing.replaces ? typing.replaces.w * scale + 6 : undefined,
                height: Math.max(1, typing.text.split('\n').length) * typing.size * TEXT_LINE * scale + 6
              }}
              onChange={(e) => setTyping({ ...typing, text: e.target.value })}
              onBlur={commitTyping}
              onKeyDown={(e) => {
                e.stopPropagation()
                if (e.key === 'Escape') setTyping(null)
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) commitTyping()
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function arrowHead(x1: number, y1: number, x2: number, y2: number, width: number): string {
  const angle = Math.atan2(y2 - y1, x2 - x1)
  const head = Math.max(8, width * 4)
  const spread = (155 * Math.PI) / 180
  const corner = (a: number): string => `${x2 + head * Math.cos(angle + a)},${y2 + head * Math.sin(angle + a)}`
  return `${x2},${y2} ${corner(spread)} ${corner(-spread)}`
}

function TextShape({ edit }: { edit: TextEdit }): ReactNode {
  const hidden = edit.replaces
  return (
    <g data-id={edit.id}>
      {/* Changing existing text: blank out the original line, as saving will. */}
      {hidden && <rect x={hidden.x - 0.5} y={hidden.y - 0.5} width={hidden.w + 1} height={hidden.h + 1} fill="#fff" />}
      <text
        x={edit.x}
        y={edit.y + edit.size * 0.8}
        fontSize={edit.size}
        fill={edit.color}
        className="pdf-text"
        style={{ fontFamily: FONT_CSS[edit.family ?? 'sans'], fontWeight: edit.bold ? 700 : 400, fontStyle: edit.italic ? 'italic' : 'normal' }}
      >
        {edit.text.split('\n').map((line, i) => (
          <tspan key={i} x={edit.x} dy={i === 0 ? 0 : edit.size * TEXT_LINE}>
            {line || ' '}
          </tspan>
        ))}
      </text>
    </g>
  )
}

/** Mirrors the engine's drawing in pdf_edit.py so that what you see is what gets saved. */
function Shape({ edit }: { edit: Edit }): ReactNode {
  switch (edit.type) {
    case 'text':
      return <TextShape edit={edit} />
    case 'highlight':
      return <rect data-id={edit.id} x={edit.x} y={edit.y} width={Math.abs(edit.w)} height={Math.abs(edit.h)} fill={edit.color} opacity={0.35} transform={flip(edit)} />
    case 'redact':
      return <rect data-id={edit.id} x={edit.x} y={edit.y} width={Math.abs(edit.w)} height={Math.abs(edit.h)} fill="#000" opacity={0.82} transform={flip(edit)} />
    case 'rect':
      return <rect data-id={edit.id} x={edit.x} y={edit.y} width={Math.abs(edit.w)} height={Math.abs(edit.h)} fill="transparent" stroke={edit.color} strokeWidth={edit.width} transform={flip(edit)} />
    case 'ellipse':
      return (
        <ellipse data-id={edit.id} cx={edit.x + edit.w / 2} cy={edit.y + edit.h / 2} rx={Math.abs(edit.w) / 2} ry={Math.abs(edit.h) / 2} fill="transparent" stroke={edit.color} strokeWidth={edit.width} />
      )
    case 'line':
    case 'arrow':
      return (
        <g data-id={edit.id}>
          {/* A wide invisible stroke makes thin lines easy to grab. */}
          <line x1={edit.x1} y1={edit.y1} x2={edit.x2} y2={edit.y2} stroke="transparent" strokeWidth={Math.max(12, edit.width)} />
          <line x1={edit.x1} y1={edit.y1} x2={edit.x2} y2={edit.y2} stroke={edit.color} strokeWidth={edit.width} strokeLinecap="round" />
          {edit.type === 'arrow' && <polygon points={arrowHead(edit.x1, edit.y1, edit.x2, edit.y2, edit.width)} fill={edit.color} />}
        </g>
      )
    case 'ink': {
      const points = edit.points.map((p) => p.join(',')).join(' ')
      return (
        <g data-id={edit.id}>
          <polyline points={points} fill="none" stroke="transparent" strokeWidth={Math.max(12, edit.width)} />
          <polyline points={points} fill="none" stroke={edit.color} strokeWidth={edit.width} strokeLinecap="round" strokeLinejoin="round" />
        </g>
      )
    }
    case 'image':
      return <image data-id={edit.id} href={edit.data_url} x={edit.x} y={edit.y} width={edit.w} height={edit.h} preserveAspectRatio="none" />
    case 'note':
      return (
        <g data-id={edit.id}>
          <title>{edit.text}</title>
          <rect x={edit.x} y={edit.y} width={20} height={20} rx={3} fill="#ffd84d" stroke="#8a6d00" strokeWidth={0.8} />
          <path d={`M${edit.x + 5} ${edit.y + 7}h10M${edit.x + 5} ${edit.y + 11}h10M${edit.x + 5} ${edit.y + 15}h6`} stroke="#8a6d00" strokeWidth={1} />
        </g>
      )
  }
}

/** While a box is being dragged up/left its w/h are negative; draw it mirrored. */
function flip(edit: { x: number; y: number; w: number; h: number }): string | undefined {
  if (edit.w >= 0 && edit.h >= 0) return undefined
  return `translate(${edit.w < 0 ? edit.w : 0} ${edit.h < 0 ? edit.h : 0})`
}

function Outline({ edit }: { edit: Edit }): ReactNode {
  const b = bounds(edit)
  const pad = 3
  return (
    <g className="pdf-outline">
      <rect x={b.x - pad} y={b.y - pad} width={b.w + pad * 2} height={b.h + pad * 2} />
      {isResizable(edit) && <circle data-id={edit.id} data-handle="se" cx={b.x + b.w} cy={b.y + b.h} r={5} />}
    </g>
  )
}
