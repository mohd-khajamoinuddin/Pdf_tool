import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'

const WIDTH = 520
const HEIGHT = 200

export interface Signature {
  data_url: string
  width: number
  height: number
}

/** Draw a signature with the mouse or a pen; returns a transparent PNG cropped to the ink. */
export function SignaturePad({ onClose }: { onClose(signature: Signature | null): void }): ReactNode {
  const canvas = useRef<HTMLCanvasElement>(null)
  const drawing = useRef(false)
  const box = useRef({ minX: WIDTH, minY: HEIGHT, maxX: 0, maxY: 0 })
  const [empty, setEmpty] = useState(true)

  useEffect(() => {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return
    ctx.lineWidth = 2.4
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.strokeStyle = '#111827'
  }, [])

  function position(e: ReactPointerEvent<HTMLCanvasElement>): [number, number] {
    const rect = e.currentTarget.getBoundingClientRect()
    return [((e.clientX - rect.left) * WIDTH) / rect.width, ((e.clientY - rect.top) * HEIGHT) / rect.height]
  }

  function extend(x: number, y: number): void {
    const b = box.current
    b.minX = Math.min(b.minX, x)
    b.minY = Math.min(b.minY, y)
    b.maxX = Math.max(b.maxX, x)
    b.maxY = Math.max(b.maxY, y)
  }

  function down(e: ReactPointerEvent<HTMLCanvasElement>): void {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drawing.current = true
    const [x, y] = position(e)
    ctx.beginPath()
    ctx.moveTo(x, y)
    extend(x, y)
  }

  function move(e: ReactPointerEvent<HTMLCanvasElement>): void {
    const ctx = canvas.current?.getContext('2d')
    if (!drawing.current || !ctx) return
    const [x, y] = position(e)
    ctx.lineTo(x, y)
    ctx.stroke()
    extend(x, y)
    setEmpty(false)
  }

  function clear(): void {
    canvas.current?.getContext('2d')?.clearRect(0, 0, WIDTH, HEIGHT)
    box.current = { minX: WIDTH, minY: HEIGHT, maxX: 0, maxY: 0 }
    setEmpty(true)
  }

  function accept(): void {
    const source = canvas.current
    if (!source || empty) return
    const pad = 6
    const b = box.current
    const x = Math.max(0, Math.floor(b.minX - pad))
    const y = Math.max(0, Math.floor(b.minY - pad))
    const width = Math.min(WIDTH, Math.ceil(b.maxX + pad)) - x
    const height = Math.min(HEIGHT, Math.ceil(b.maxY + pad)) - y
    const cropped = document.createElement('canvas')
    cropped.width = width
    cropped.height = height
    cropped.getContext('2d')?.drawImage(source, x, y, width, height, 0, 0, width, height)
    onClose({ data_url: cropped.toDataURL('image/png'), width, height })
  }

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose(null)}>
      <div className="dialog sig-dialog" role="dialog" aria-modal="true" aria-label="Draw signature" onKeyDown={(e) => e.key === 'Escape' && onClose(null)}>
        <h2>Draw your signature</h2>
        <p className="muted">
          This places a picture of your signature on the page. It is not a certificate-based digital signature and does not
          prove who signed.
        </p>
        <canvas
          ref={canvas}
          className="sig-canvas"
          width={WIDTH}
          height={HEIGHT}
          onPointerDown={down}
          onPointerMove={move}
          onPointerUp={() => (drawing.current = false)}
          onPointerCancel={() => (drawing.current = false)}
        />
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={clear} disabled={empty}>
            Clear
          </button>
          <span className="spacer" />
          <button type="button" className="btn" onClick={() => onClose(null)}>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={accept} disabled={empty}>
            Place signature
          </button>
        </div>
      </div>
    </div>
  )
}
