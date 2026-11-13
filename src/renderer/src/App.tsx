import { lazy, Suspense, useState, type ReactNode } from 'react'
import { Icon } from './components/Icon'
import { baseName } from './lib/files'
import { MODULES, type ModuleId } from './lib/modules'
import { useServices } from './lib/services'
import { Home } from './modules/Home'

// Each editor is a separate chunk, loaded the first time its workspace is opened,
// so launching the app does not pay for the spreadsheet engine or the slide canvas.
const PdfStudio = lazy(() => import('./modules/PdfStudio').then((m) => ({ default: m.PdfStudio })))
const Sheets = lazy(() => import('./modules/Sheets').then((m) => ({ default: m.Sheets })))
const Documents = lazy(() => import('./modules/Documents').then((m) => ({ default: m.Documents })))
const Slides = lazy(() => import('./modules/Slides').then((m) => ({ default: m.Slides })))

const WORKSPACES = [
  { id: 'pdf', View: PdfStudio },
  { id: 'sheets', View: Sheets },
  { id: 'docs', View: Documents },
  { id: 'slides', View: Slides }
] as const

export function App(): ReactNode {
  const [active, setActive] = useState<ModuleId>('home')
  const [opened, setOpened] = useState<ReadonlySet<ModuleId>>(new Set())

  function navigate(id: ModuleId): void {
    setActive(id)
    setOpened((seen) => (seen.has(id) ? seen : new Set(seen).add(id)))
  }
  const { engine } = useServices()

  return (
    <div className="app">
      <nav className="nav" aria-label="Modules">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="layers" size={20} />
          </span>
          DocSuite
        </div>
        {MODULES.map((m) => (
          <button
            key={m.id}
            className={`nav-item mod-${m.id}${active === m.id ? ' active' : ''}`}
            aria-current={active === m.id ? 'page' : undefined}
            onClick={() => navigate(m.id)}
          >
            <Icon name={m.icon} />
            {m.label}
          </button>
        ))}
        <div className="nav-foot">
          <Icon name="shield" size={16} />
          <span>
            <strong>Offline by design.</strong> Files are processed on this computer and never leave it.
          </span>
        </div>
      </nav>

      {/* Once opened, a workspace stays mounted so open files and edits survive switching tabs. */}
      <main className="workspace">
        <section hidden={active !== 'home'}>
          <Home onNavigate={navigate} />
        </section>
        {WORKSPACES.map(({ id, View }) => (
          <section key={id} hidden={active !== id} className={`mod-${id}`}>
            {opened.has(id) && (
              <Suspense fallback={<div className="loading">Loading…</div>}>
                <View />
              </Suspense>
            )}
          </section>
        ))}
      </main>

      <footer className="statusbar">
        <span className={`dot ${engine.state}`} />
        {engine.state === 'ready' && 'Processing engine ready'}
        {engine.state === 'starting' && 'Starting processing engine…'}
        {engine.state === 'stopped' && `Processing engine stopped${engine.detail ? ` — ${engine.detail}` : ''}`}
        <span className="spacer" />
        <Icon name="shield" size={14} /> Network access disabled
      </footer>

      <JobTray />
    </div>
  )
}

function JobTray(): ReactNode {
  const { jobs, dismissJob } = useServices()
  if (jobs.length === 0) return null
  return (
    <div className="tray" role="status" aria-live="polite">
      {jobs.map((job) => (
        <div key={job.id} className={`job ${job.status}`}>
          <div className="job-head">
            {job.status === 'done' && <Icon name="check" size={16} />}
            {job.status === 'error' && <Icon name="alert" size={16} />}
            <strong title={job.label}>{job.label}</strong>
            <button className="icon-btn" aria-label="Dismiss" onClick={() => dismissJob(job.id)}>
              <Icon name="close" size={14} />
            </button>
          </div>
          {job.status === 'running' ? (
            <>
              <div className="bar">
                <div style={{ width: `${Math.round(job.progress * 100)}%` }} />
              </div>
              <small className="muted">{job.message}</small>
            </>
          ) : (
            <small className={job.status === 'error' ? 'error-text' : 'muted'}>{job.message}</small>
          )}
          {job.status === 'done' && job.output && (
            <button className="link" onClick={() => void window.suite.revealInFolder(job.output as string)}>
              Show {baseName(job.output)} in folder
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
