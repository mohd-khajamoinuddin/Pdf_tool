import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

export interface MenuItem {
  icon?: IconName
  label: string
  onSelect(): void
}

/** A toolbar button that opens a small list of actions. */
export function MenuButton(props: { icon: IconName; label: string; items: MenuItem[]; disabled?: boolean }): ReactNode {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: Event): void => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  return (
    <div className="menu" ref={root}>
      <button className="btn" disabled={props.disabled} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name={props.icon} size={16} />
        {props.label}
        <Icon name="chevron" size={14} />
      </button>
      {open && (
        <div className="menu-list" role="menu">
          {props.items.map((item) => (
            <button
              key={item.label}
              role="menuitem"
              onClick={() => {
                setOpen(false)
                item.onSelect()
              }}
            >
              {item.icon && <Icon name={item.icon} size={16} />}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
