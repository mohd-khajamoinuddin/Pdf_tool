import type { ReactNode } from 'react'
import { baseName } from '../lib/files'
import { Icon, type IconName } from './Icon'

/** Shared chrome for the four editor modules: title row, toolbar, optional notice. */
export function ModuleFrame(props: {
  title: string
  file?: string | null
  dirty?: boolean
  toolbar: ReactNode
  notice?: ReactNode
  children: ReactNode
}): ReactNode {
  return (
    <div className="module">
      <header className="module-head">
        <h1>{props.title}</h1>
        {props.file && (
          <span className="file-chip" title={props.file}>
            {baseName(props.file)}
            {props.dirty && <em> · edited</em>}
          </span>
        )}
      </header>
      <div className="toolbar" role="toolbar">
        {props.toolbar}
      </div>
      {props.notice && <div className="notice">{props.notice}</div>}
      <div className="module-body">{props.children}</div>
    </div>
  )
}

export function ToolButton(props: {
  icon: IconName
  label: string
  onClick(): void
  disabled?: boolean
  primary?: boolean
}): ReactNode {
  return (
    <button className={`btn${props.primary ? ' primary' : ''}`} disabled={props.disabled} onClick={props.onClick}>
      <Icon name={props.icon} size={16} />
      {props.label}
    </button>
  )
}

export function EmptyState(props: { icon: IconName; title: string; body: string; children?: ReactNode }): ReactNode {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={props.icon} size={30} />
      </span>
      <h2>{props.title}</h2>
      <p className="muted">{props.body}</p>
      <div className="empty-actions">{props.children}</div>
    </div>
  )
}
