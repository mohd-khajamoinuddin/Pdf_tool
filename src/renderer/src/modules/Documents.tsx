import { EditorContent, useEditor } from '@tiptap/react'
import { useState, type ReactNode } from 'react'
import type { FileFilter } from '../../../shared/api'
import { ModuleFrame, ToolButton } from '../components/Frame'
import { Icon } from '../components/Icon'
import { MenuButton } from '../components/Menu'
import { baseName, FILTERS, samePath, withExt } from '../lib/files'
import { printHtmlToPdf } from '../lib/print'
import { call, useServices } from '../lib/services'
import { countMatches, extensions, replaceAll, wordCount, type DocJson } from './docs/editor'
import { TEMPLATES } from './docs/templates'
import { Toolbar } from './docs/Toolbar'
import './docs/docs.css'

const OPEN_FILTERS: FileFilter[] = [{ name: 'Documents', extensions: ['docx', 'odt', 'rtf', 'txt', 'md'] }]
const SAVE_FILTERS: FileFilter[] = [
  { name: 'Word document', extensions: ['docx'] },
  { name: 'OpenDocument text', extensions: ['odt'] },
  { name: 'Rich Text Format', extensions: ['rtf'] },
  { name: 'Markdown', extensions: ['md'] },
  { name: 'Plain text', extensions: ['txt'] }
]
const DATA_FILTERS: FileFilter[] = [{ name: 'Data files', extensions: ['csv', 'xlsx'] }]

interface DocFile {
  path: string | null
  /** Opened from a file this app did not write: saving over it could drop content we did not import. */
  foreign: boolean
  /** What the engine could not import (footnotes, text boxes, …). */
  notes: string[]
}

interface OpenResult {
  content: DocJson
  header: string
  footer: string
  notes: string[]
}

interface MergeData {
  path: string
  fields: string[]
  records: number
  sample: Record<string, string>
}

/** Print styles for PDF export: A4 with 20 mm margins, same typography as the on-screen page. */
const PRINT_CSS = `
  @page { size: A4; margin: 20mm; }
  @media print { #print-root { font: 11pt/1.5 Calibri, 'Segoe UI', Arial, sans-serif; color: #000; } }
`

export function Documents(): ReactNode {
  const { run, notify, ask } = useServices()
  const [file, setFile] = useState<DocFile | null>(null)
  const [dirty, setDirty] = useState(false)
  const [header, setHeader] = useState('')
  const [footer, setFooter] = useState('')
  const [merge, setMerge] = useState<MergeData | null>(null)
  const [combined, setCombined] = useState(false)

  const editor = useEditor({
    extensions,
    content: '',
    // The toolbar reads the selection's formatting, so it has to re-render with it.
    shouldRerenderOnTransaction: true,
    onUpdate: () => setDirty(true)
  })

  function show(content: DocJson, next: DocFile, head = '', foot = ''): void {
    editor.commands.setContent(content, { emitUpdate: false })
    editor.commands.focus('start')
    setFile(next)
    setHeader(head)
    setFooter(foot)
    setDirty(false)
  }

  async function open(): Promise<void> {
    const [path] = await window.suite.openFiles({ title: 'Open document', filters: OPEN_FILTERS })
    if (!path) return
    const result = await run<OpenResult>(`Open ${baseName(path)}`, 'doc.open', { input: path })
    if (result) show(result.content, { path, foreign: true, notes: result.notes }, result.header, result.footer)
  }

  async function saveAs(): Promise<void> {
    if (!file) return
    const output = await window.suite.saveFile({
      title: 'Save document as',
      defaultPath: file.path ? withExt(file.path, 'docx', file.foreign ? '-edited' : '') : 'Document.docx',
      filters: SAVE_FILTERS
    })
    if (!output) return
    if (file.foreign && file.path && samePath(file.path, output)) {
      return notify('Save document', 'Choose a new name so the original file, and anything in it this editor did not import, is kept.', 'error')
    }
    const saved = await run(`Save ${baseName(output)}`, 'doc.save', { output, content: editor.getJSON(), header, footer })
    if (saved && /\.docx$/i.test(output)) {
      // Only .docx holds everything on screen (header and footer included); other formats are exports.
      setFile({ path: output, foreign: false, notes: [] })
      setDirty(false)
    }
  }

  async function exportPdf(): Promise<void> {
    if (!file) return
    const output = await window.suite.saveFile({
      title: 'Export PDF as',
      defaultPath: file.path ? withExt(file.path, 'pdf') : 'Document.pdf',
      filters: FILTERS.pdf
    })
    if (!output) return
    const result = await printHtmlToPdf(output, `<div class="doc-content">${editor.getHTML()}</div>`, PRINT_CSS, { pageSize: 'A4' })
    if (result.ok) notify(`${baseName(output)}`, 'PDF exported. Header and footer text is saved to .docx only.')
    else notify('Export PDF', result.message, 'error')
  }

  async function insertImage(): Promise<void> {
    const [path] = await window.suite.openFiles({ title: 'Insert image', filters: FILTERS.images })
    if (!path) return
    try {
      const img = await call<{ data_url: string; width: number; height: number }>('doc.image_data_url', { input: path })
      const width = Math.min(img.width, 560)
      editor
        .chain()
        .focus()
        .setImage({ src: img.data_url, width, height: Math.round((img.height * width) / img.width) })
        .run()
    } catch (err) {
      notify('Insert image', err instanceof Error ? err.message : String(err), 'error')
    }
  }

  async function findReplace(): Promise<void> {
    const answer = await ask({
      title: 'Find and replace',
      fields: [
        { name: 'find', label: 'Find' },
        { name: 'replace', label: 'Replace with', optional: true },
        { name: 'matchCase', label: 'Match case', type: 'checkbox', initial: 'false' }
      ],
      confirm: 'Replace all'
    })
    if (!answer) return
    const matchCase = answer.matchCase === 'true'
    const found = countMatches(editor, answer.find, matchCase)
    const done = found ? replaceAll(editor, answer.find, answer.replace, matchCase) : 0
    notify('Find and replace', done ? `Replaced ${done} occurrence${done > 1 ? 's' : ''}.` : `"${answer.find}" was not found.`, done ? 'done' : 'error')
  }

  async function pageSetup(): Promise<void> {
    const answer = await ask({
      title: 'Header and footer',
      body: 'Shown at the top and bottom of every page when the document is saved as .docx.',
      fields: [
        { name: 'header', label: 'Header text', initial: header, optional: true },
        { name: 'footer', label: 'Footer text', initial: footer, optional: true }
      ],
      confirm: 'Apply'
    })
    if (!answer) return
    if (answer.header !== header || answer.footer !== footer) setDirty(true)
    setHeader(answer.header)
    setFooter(answer.footer)
  }

  // ---- mail merge
  async function pickMergeData(): Promise<void> {
    const [path] = await window.suite.openFiles({ title: 'Choose the data file (first row = field names)', filters: DATA_FILTERS })
    if (!path) return
    try {
      const info = await call<Omit<MergeData, 'path'>>('doc.merge_fields', { input: path })
      setMerge({ path, ...info })
    } catch (err) {
      notify('Mail merge', err instanceof Error ? err.message : String(err), 'error')
    }
  }

  async function generateMerge(): Promise<void> {
    if (!merge || !file) return
    const output_dir = await window.suite.openFolder({ title: 'Choose a folder for the merged documents' })
    if (!output_dir) return
    await run(`Mail merge: ${merge.records} record${merge.records === 1 ? '' : 's'}`, 'doc.mail_merge', {
      content: editor.getJSON(),
      input: merge.path,
      output_dir,
      base_name: file.path ? baseName(file.path).replace(/\.[^.]+$/, '') : 'merged',
      combined,
      header,
      footer
    })
  }

  const notes = file?.notes ?? []

  return (
    <ModuleFrame
      title="Documents"
      file={file ? (file.path ?? 'Untitled document') : null}
      dirty={dirty}
      notice={notes.length > 0 && `Not imported from the original, and so not in a saved copy: ${notes.join(' · ')}`}
      toolbar={
        <>
          <MenuButton
            icon="plus"
            label="New"
            items={TEMPLATES.map((tpl) => ({
              label: tpl.name,
              onSelect: () => show(tpl.content, { path: null, foreign: false, notes: [] })
            }))}
          />
          <ToolButton icon="open" label="Open" primary={!file} onClick={() => void open()} />
          <ToolButton icon="save" label="Save as…" primary={!!file && dirty} disabled={!file} onClick={() => void saveAs()} />
          <span className="sep" />
          <ToolButton icon="doc" label="Header & footer" disabled={!file} onClick={() => void pageSetup()} />
          <ToolButton icon="mail" label="Mail merge" disabled={!file} onClick={() => (merge ? setMerge(null) : void pickMergeData())} />
          <ToolButton icon="pdf" label="Export PDF" disabled={!file} onClick={() => void exportPdf()} />
        </>
      }
    >
      <div className="doc-work">
        {!file ? (
          <div className="doc-gallery">
            <h2>Start a document</h2>
            <p className="muted">Pick a template, or open a .docx, .odt, .rtf, .md or .txt file.</p>
            <div className="doc-templates">
              {TEMPLATES.map((tpl) => (
                <button key={tpl.id} className="doc-template" onClick={() => show(tpl.content, { path: null, foreign: false, notes: [] })}>
                  <span className="doc-template-page">
                    <Icon name="doc" size={26} />
                  </span>
                  <strong>{tpl.name}</strong>
                  <small className="muted">{tpl.blurb}</small>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <Toolbar editor={editor} onInsertImage={() => void insertImage()} onFind={() => void findReplace()} />
            <div className="doc-main">
              <div className="doc-scroll">
                <div className="doc-page">
                  {header && <div className="doc-headfoot">{header}</div>}
                  <EditorContent editor={editor} className="doc-content" spellCheck={false} />
                  {footer && <div className="doc-headfoot foot">{footer}</div>}
                </div>
              </div>
              {merge && (
                <aside className="doc-merge" aria-label="Mail merge">
                  <header>
                    <h3>Mail merge</h3>
                    <button className="icon-btn" aria-label="Close mail merge" onClick={() => setMerge(null)}>
                      <Icon name="close" size={14} />
                    </button>
                  </header>
                  <p className="muted small">
                    {baseName(merge.path)} · {merge.records} record{merge.records === 1 ? '' : 's'}. Click a field to insert its
                    placeholder at the cursor.
                  </p>
                  <div className="doc-fields">
                    {merge.fields.map((field) => (
                      <button
                        key={field}
                        className="doc-field"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => editor.chain().focus().insertContent(`{{${field}}}`).run()}
                      >
                        <code>{`{{${field}}}`}</code>
                        <small className="muted">{merge.sample[field] ?? ''}</small>
                      </button>
                    ))}
                  </div>
                  <label className="check">
                    <input type="checkbox" checked={combined} onChange={(e) => setCombined(e.target.checked)} />
                    One combined document
                  </label>
                  <button className="btn primary" disabled={merge.records === 0} onClick={() => void generateMerge()}>
                    <Icon name="play" size={14} /> Generate…
                  </button>
                  <button className="btn" onClick={() => void pickMergeData()}>
                    Change data file
                  </button>
                </aside>
              )}
            </div>
            <div className="doc-status">
              {wordCount(editor).toLocaleString()} words
              {(header || footer) && <span> · header/footer set</span>}
            </div>
          </>
        )}
      </div>
    </ModuleFrame>
  )
}
