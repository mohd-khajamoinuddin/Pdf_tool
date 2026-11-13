import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { Deck } from './model'
import { SlideView } from './SlideView'

/** Full-screen presentation: arrows / space / click to advance, Esc to leave. */
export function SlideShow({ deck, start, onClose }: { deck: Deck; start: number; onClose(): void }): ReactNode {
  const root = useRef<HTMLDivElement>(null)
  const [index, setIndex] = useState(start)
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight })

  useEffect(() => {
    const el = root.current
    if (!el) return
    el.focus()
    // Full screen is a nicety; the show also works inside the window if it is refused.
    el.requestFullscreen?.().catch(() => undefined)
    const resize = (): void => setSize({ w: window.innerWidth, h: window.innerHeight })
    const left = (): void => {
      if (!document.fullscreenElement) onClose() // Esc in full screen exits it first; follow that
    }
    window.addEventListener('resize', resize)
    document.addEventListener('fullscreenchange', left)
    return () => {
      window.removeEventListener('resize', resize)
      document.removeEventListener('fullscreenchange', left)
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined)
    }
  }, [onClose])

  const last = deck.slides.length - 1
  const go = (delta: number): void => setIndex((i) => Math.min(last, Math.max(0, i + delta)))
  const slide = deck.slides[index]
  const scale = Math.min(size.w / deck.width, size.h / deck.height)

  return (
    <div
      ref={root}
      className="sl-show"
      tabIndex={-1}
      role="dialog"
      aria-label="Slide show"
      onClick={() => (index === last ? onClose() : go(1))}
      onKeyDown={(e) => {
        e.stopPropagation()
        if (e.key === 'Escape') onClose()
        else if (['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter'].includes(e.key)) go(1)
        else if (['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(e.key)) go(-1)
        else if (e.key === 'Home') setIndex(0)
        else if (e.key === 'End') setIndex(last)
      }}
    >
      {/* Re-keyed per slide so the entrance animation plays on every change. */}
      <div key={slide.id} className={`sl-show-slide tr-${slide.transition.type}`} style={{ animationDuration: `${slide.transition.duration}s` }}>
        <SlideView slide={slide} width={deck.width} height={deck.height} scale={scale} />
      </div>
      <div className="sl-show-count">
        {index + 1} / {deck.slides.length}
      </div>
    </div>
  )
}
