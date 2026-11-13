import type { ReactNode } from 'react'
import { Icon, type IconName } from '../components/Icon'
import { usePdfActions } from '../lib/actions'
import { MODULES, type ModuleId } from '../lib/modules'

export function Home({ onNavigate }: { onNavigate(id: ModuleId): void }): ReactNode {
  const pdf = usePdfActions()

  const quick: { icon: IconName; label: string; hint: string; run(): void }[] = [
    { icon: 'word', label: 'PDF to Word', hint: 'Editable .docx with headings and tables', run: () => void pdf.toWord() },
    { icon: 'merge', label: 'Merge PDFs', hint: 'Join several files into one', run: () => void pdf.merge() },
    { icon: 'image', label: 'Images to PDF', hint: 'One image per page', run: () => void pdf.imagesToPdf() },
    { icon: 'text', label: 'PDF to Markdown', hint: 'Text and tables as .md', run: () => void pdf.toMarkdown() },
    { icon: 'image', label: 'PDF to images', hint: 'A PNG for every page', run: () => void pdf.toImages() },
    { icon: 'layers', label: 'Batch PDF to Word', hint: 'Convert a whole set at once', run: () => void pdf.batchToWord() }
  ]

  return (
    <div className="home">
      <header className="home-head">
        <h1>What would you like to work on?</h1>
        <p className="muted">Everything runs on this computer. No account, no upload, no internet connection needed.</p>
      </header>

      <h2 className="section-title">Workspaces</h2>
      <div className="cards">
        {MODULES.filter((m) => m.id !== 'home').map((m) => (
          <button key={m.id} className={`card mod-${m.id}`} onClick={() => onNavigate(m.id)}>
            <span className="card-icon">
              <Icon name={m.icon} size={24} />
            </span>
            <strong>{m.label}</strong>
            <span className="muted">{m.blurb}</span>
          </button>
        ))}
      </div>

      <h2 className="section-title">Quick actions</h2>
      <div className="quick">
        {quick.map((q) => (
          <button key={q.label} className="quick-item" onClick={q.run}>
            <Icon name={q.icon} size={20} />
            <span>
              <strong>{q.label}</strong>
              <small className="muted">{q.hint}</small>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
