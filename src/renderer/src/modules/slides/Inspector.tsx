import type { ReactNode } from 'react'
import { Icon, type IconName } from '../../components/Icon'
import { FONTS, isLine, THEMES, TRANSITIONS, type El, type ShapeEl, type Slide, type TextEl, type TransitionType } from './model'

export type Align = 'left' | 'center' | 'right' | 'top' | 'middle' | 'bottom'

interface Props {
  slide: Slide
  selection: El[]
  ratio: '16:9' | '4:3'
  onElement(patch: Partial<TextEl> & Partial<ShapeEl>): void
  onSlide(patch: Partial<Pick<Slide, 'background' | 'transition'>>): void
  onTheme(themeId: string): void
  onRatio(ratio: '16:9' | '4:3'): void
  onAlign(how: Align): void
  onOrder(direction: 'front' | 'back'): void
  onDuplicate(): void
  onDelete(): void
}

function Num(props: { label: string; value: number; min?: number; step?: number; onChange(value: number): void }): ReactNode {
  return (
    <label className="sl-num">
      <span>{props.label}</span>
      <input
        type="number"
        value={Math.round(props.value * 10) / 10}
        min={props.min}
        step={props.step ?? 1}
        onChange={(e) => {
          const n = Number(e.target.value)
          if (Number.isFinite(n)) props.onChange(n)
        }}
      />
    </label>
  )
}

function Colour(props: { label: string; value: string | null; allowNone?: boolean; onChange(value: string | null): void }): ReactNode {
  return (
    <div className="sl-colour">
      <span>{props.label}</span>
      <input type="color" aria-label={props.label} value={props.value ?? '#ffffff'} onChange={(e) => props.onChange(e.target.value)} />
      {props.allowNone && (
        <button className={`sl-chip${props.value === null ? ' active' : ''}`} onClick={() => props.onChange(null)}>
          None
        </button>
      )}
    </div>
  )
}

function IconToggle(props: { icon?: IconName; glyph?: string; label: string; active?: boolean; onClick(): void }): ReactNode {
  return (
    <button className={`sl-toggle${props.active ? ' active' : ''}`} title={props.label} aria-label={props.label} aria-pressed={props.active} onClick={props.onClick}>
      {props.icon ? <Icon name={props.icon} size={15} /> : <span className={`glyph glyph-${props.glyph}`}>{props.glyph}</span>}
    </button>
  )
}

/** Right-hand panel: properties of the selection, or of the slide and deck when nothing is selected. */
export function Inspector(props: Props): ReactNode {
  const { selection, slide } = props
  const first = selection[0]

  if (!first) {
    return (
      <aside className="sl-inspector" aria-label="Slide properties">
        <h3>Slide</h3>
        <Colour label="Background" value={slide.background} onChange={(v) => props.onSlide({ background: v ?? '#ffffff' })} />
        <label className="sl-field">
          <span>Transition</span>
          <select
            aria-label="Transition"
            value={slide.transition.type}
            onChange={(e) => props.onSlide({ transition: { ...slide.transition, type: e.target.value as TransitionType } })}
          >
            {TRANSITIONS.map((t) => (
              <option key={t} value={t}>
                {t[0].toUpperCase() + t.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <label className="sl-field">
          <span>Speed</span>
          <select
            aria-label="Transition speed"
            value={slide.transition.duration}
            disabled={slide.transition.type === 'none'}
            onChange={(e) => props.onSlide({ transition: { ...slide.transition, duration: Number(e.target.value) } })}
          >
            <option value={0.3}>Fast</option>
            <option value={0.6}>Medium</option>
            <option value={1}>Slow</option>
          </select>
        </label>

        <h3>Deck</h3>
        <label className="sl-field">
          <span>Theme</span>
          <select aria-label="Theme" value="" onChange={(e) => e.target.value && props.onTheme(e.target.value)}>
            <option value="">Apply a theme…</option>
            {THEMES.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="sl-field">
          <span>Slide size</span>
          <select aria-label="Slide size" value={props.ratio} onChange={(e) => props.onRatio(e.target.value as '16:9' | '4:3')}>
            <option value="16:9">Widescreen 16:9</option>
            <option value="4:3">Standard 4:3</option>
          </select>
        </label>
        <p className="muted small">Select an element to edit it. Double-click text to type. Shift-click selects several.</p>
      </aside>
    )
  }

  const texts = selection.filter((e): e is TextEl => e.type === 'text')
  const shapes = selection.filter((e): e is ShapeEl => e.type === 'shape')
  const text = texts[0]
  const shape = shapes[0]
  const single = selection.length === 1

  return (
    <aside className="sl-inspector" aria-label="Element properties">
      <h3>{selection.length > 1 ? `${selection.length} elements` : first.type === 'shape' ? 'Shape' : first.type === 'text' ? 'Text' : 'Image'}</h3>

      {text && (
        <>
          <label className="sl-field">
            <span>Font</span>
            <select aria-label="Font" value={text.fontFamily} onChange={(e) => props.onElement({ fontFamily: e.target.value })}>
              {(FONTS.includes(text.fontFamily) ? FONTS : [text.fontFamily, ...FONTS]).map((f) => (
                <option key={f}>{f}</option>
              ))}
            </select>
          </label>
          <div className="sl-row">
            <Num label="Size" value={text.fontSize} min={6} onChange={(v) => props.onElement({ fontSize: Math.max(6, v) })} />
            <Colour label="Colour" value={text.color} onChange={(v) => props.onElement({ color: v ?? '#000000' })} />
          </div>
          <div className="sl-toggles">
            <IconToggle glyph="B" label="Bold" active={text.bold} onClick={() => props.onElement({ bold: !text.bold })} />
            <IconToggle glyph="I" label="Italic" active={text.italic} onClick={() => props.onElement({ italic: !text.italic })} />
            <IconToggle glyph="U" label="Underline" active={text.underline} onClick={() => props.onElement({ underline: !text.underline })} />
            <span className="sep" />
            <IconToggle icon="alignLeft" label="Align text left" active={text.align === 'left'} onClick={() => props.onElement({ align: 'left' })} />
            <IconToggle icon="alignCenter" label="Align text centre" active={text.align === 'center'} onClick={() => props.onElement({ align: 'center' })} />
            <IconToggle icon="alignRight" label="Align text right" active={text.align === 'right'} onClick={() => props.onElement({ align: 'right' })} />
            <span className="sep" />
            <IconToggle icon="listBullet" label="Bullets" active={text.bullets} onClick={() => props.onElement({ bullets: !text.bullets })} />
          </div>
        </>
      )}

      {shape && (
        <>
          {!isLine(shape) && <Colour label="Fill" value={shape.fill} allowNone onChange={(v) => props.onElement({ fill: v })} />}
          <Colour label="Outline" value={shape.stroke} allowNone={!isLine(shape)} onChange={(v) => props.onElement({ stroke: v, strokeWidth: v ? Math.max(shape.strokeWidth, 1) : 0 })} />
          <div className="sl-row">
            <Num label="Outline width" value={shape.strokeWidth} min={0} step={0.5} onChange={(v) => props.onElement({ strokeWidth: Math.max(0, v) })} />
            <Num label="Opacity %" value={shape.opacity * 100} min={5} step={5} onChange={(v) => props.onElement({ opacity: Math.min(1, Math.max(0.05, v / 100)) })} />
          </div>
        </>
      )}

      {single && (
        <>
          <h3>Position</h3>
          <div className="sl-row">
            <Num label="X" value={first.x} onChange={(v) => props.onElement({ x: v })} />
            <Num label="Y" value={first.y} onChange={(v) => props.onElement({ y: v })} />
          </div>
          <div className="sl-row">
            <Num label="Width" value={first.w} onChange={(v) => props.onElement({ w: v })} />
            <Num label="Height" value={first.h} onChange={(v) => props.onElement({ h: v })} />
          </div>
          {!isLine(first) && <Num label="Rotation °" value={first.rotation} onChange={(v) => props.onElement({ rotation: v })} />}
        </>
      )}

      <h3>Arrange</h3>
      <div className="sl-toggles">
        <IconToggle icon="alignLeft" label="Align left edges" onClick={() => props.onAlign('left')} />
        <IconToggle icon="alignCenter" label="Centre horizontally" onClick={() => props.onAlign('center')} />
        <IconToggle icon="alignRight" label="Align right edges" onClick={() => props.onAlign('right')} />
        <span className="sep" />
        <IconToggle icon="up" label="Align top edges" onClick={() => props.onAlign('top')} />
        <IconToggle icon="rule" label="Centre vertically" onClick={() => props.onAlign('middle')} />
        <IconToggle icon="down" label="Align bottom edges" onClick={() => props.onAlign('bottom')} />
      </div>
      <div className="sl-actions">
        <button className="btn" onClick={() => props.onOrder('front')}>
          <Icon name="front" size={15} /> Forward
        </button>
        <button className="btn" onClick={() => props.onOrder('back')}>
          <Icon name="back" size={15} /> Backward
        </button>
        <button className="btn" onClick={props.onDuplicate}>
          <Icon name="copy" size={15} /> Duplicate
        </button>
        <button className="btn" onClick={props.onDelete}>
          <Icon name="trash" size={15} /> Delete
        </button>
      </div>
    </aside>
  )
}
