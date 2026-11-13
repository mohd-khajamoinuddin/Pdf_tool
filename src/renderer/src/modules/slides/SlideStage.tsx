import type Konva from 'konva'
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Group, Layer, Rect, Stage, Transformer } from 'react-konva'
import { isLine, type El, type Slide } from './model'
import { ElementShape, placement } from './SlideView'

export type Patch = { id: string } & Partial<Pick<El, 'x' | 'y' | 'w' | 'h' | 'rotation'>>

interface Props {
  slide: Slide
  width: number
  height: number
  selected: string[]
  onSelect(ids: string[]): void
  /** Geometry changes from dragging / resizing / rotating, for one or several elements at once. */
  onPatch(patches: Patch[]): void
  onText(id: string, text: string): void
}

const round = (n: number): number => Math.round(n * 100) / 100

/** Read a node's geometry back into model units, folding any scale into width/height. */
function geometry(node: Konva.Node, el: El): Patch {
  const sx = node.scaleX()
  const sy = node.scaleY()
  node.scaleX(1)
  node.scaleY(1)
  if (isLine(el)) return { id: el.id, x: round(node.x()), y: round(node.y()), w: round(el.w * sx), h: round(el.h * sy) }
  const w = Math.max(4, el.w * sx)
  const h = Math.max(4, el.h * sy)
  return { id: el.id, x: round(node.x() - w / 2), y: round(node.y() - h / 2), w: round(w), h: round(h), rotation: round(node.rotation()) }
}

/** The editable slide: select, drag, resize, rotate, and type into text boxes. */
export function SlideStage(props: Props): ReactNode {
  const { slide, width, height, selected } = props
  const frame = useRef<HTMLDivElement>(null)
  const layer = useRef<Konva.Layer>(null)
  const transformer = useRef<Konva.Transformer>(null)
  const [scale, setScale] = useState(0.8)
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  // Zoom to fit, and re-fit whenever the workspace is resized or shown again.
  useLayoutEffect(() => {
    const el = frame.current
    if (!el) return
    const fit = (): void => {
      if (el.clientWidth === 0) return // hidden workspace: keep the last scale
      setScale(Math.max(0.1, Math.min((el.clientWidth - 48) / width, (el.clientHeight - 48) / height)))
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(el)
    return () => observer.disconnect()
  }, [width, height])

  useEffect(() => {
    const tr = transformer.current
    if (!tr || !layer.current) return
    const nodes = selected.map((id) => layer.current?.findOne(`#${id}`)).filter((n): n is Konva.Node => !!n && n.id() !== editing)
    tr.nodes(nodes)
    tr.getLayer()?.batchDraw()
  }, [selected, slide, editing])

  useEffect(() => setEditing(null), [slide.id])

  function commitGeometry(): void {
    const patches: Patch[] = []
    for (const node of transformer.current?.nodes() ?? []) {
      const el = slide.elements.find((e) => e.id === node.id())
      if (!el) continue
      const next = geometry(node, el)
      if (next.x !== el.x || next.y !== el.y || (next.w ?? el.w) !== el.w || (next.h ?? el.h) !== el.h || (next.rotation ?? el.rotation) !== el.rotation) {
        patches.push(next)
      }
    }
    if (patches.length) props.onPatch(patches)
  }

  function pick(el: El, additive: boolean): void {
    if (additive) props.onSelect(selected.includes(el.id) ? selected.filter((id) => id !== el.id) : [...selected, el.id])
    else if (!selected.includes(el.id)) props.onSelect([el.id])
  }

  function finishEditing(save: boolean): void {
    if (editing && save) props.onText(editing, draft)
    setEditing(null)
  }

  const typing = slide.elements.find((e) => e.id === editing)
  const anyLine = slide.elements.some((e) => selected.includes(e.id) && isLine(e))
  const onlyImages = selected.length > 0 && slide.elements.filter((e) => selected.includes(e.id)).every((e) => e.type === 'image')

  return (
    <div className="sl-frame" ref={frame}>
      <div className="sl-canvas" style={{ width: width * scale, height: height * scale }}>
        <Stage
          width={width * scale}
          height={height * scale}
          scaleX={scale}
          scaleY={scale}
          onMouseDown={(e) => {
            if (e.target === e.target.getStage() || e.target.name() === 'background') props.onSelect([])
          }}
        >
          <Layer ref={layer}>
            <Rect name="background" width={width} height={height} fill={slide.background} />
            {slide.elements.map((el) => (
              <Group
                key={el.id}
                id={el.id}
                {...placement(el)}
                draggable={editing !== el.id}
                onMouseDown={(e) => pick(el, e.evt.shiftKey || e.evt.ctrlKey)}
                onDragEnd={commitGeometry}
                onDblClick={() => {
                  if (el.type !== 'text') return
                  setDraft(el.text)
                  setEditing(el.id)
                }}
              >
                <ElementShape el={el} hideText={editing === el.id} />
              </Group>
            ))}
            <Transformer
              ref={transformer}
              rotateEnabled={!anyLine}
              keepRatio={onlyImages}
              rotationSnaps={[0, 45, 90, 135, 180, 225, 270, 315]}
              anchorSize={8}
              borderStroke="#2e6fdb"
              anchorStroke="#2e6fdb"
              boundBoxFunc={(before, after) => (Math.abs(after.width) < 6 || Math.abs(after.height) < 6 ? before : after)}
              onTransformEnd={commitGeometry}
            />
          </Layer>
        </Stage>
        {typing?.type === 'text' && (
          <textarea
            className="sl-typing"
            autoFocus
            spellCheck={false}
            value={draft}
            style={{
              left: typing.x * scale,
              top: typing.y * scale,
              width: typing.w * scale,
              height: typing.h * scale,
              transform: `rotate(${typing.rotation}deg)`,
              fontFamily: typing.fontFamily,
              fontSize: typing.fontSize * scale,
              fontWeight: typing.bold ? 700 : 400,
              fontStyle: typing.italic ? 'italic' : 'normal',
              color: typing.color,
              textAlign: typing.align
            }}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => finishEditing(true)}
            onKeyDown={(e) => {
              e.stopPropagation()
              if (e.key === 'Escape') finishEditing(false)
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) finishEditing(true)
            }}
          />
        )}
      </div>
    </div>
  )
}
