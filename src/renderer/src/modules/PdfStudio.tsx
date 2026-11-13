import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { EmptyState, ModuleFrame, ToolButton } from '../components/Frame'
import { Icon, type IconName } from '../components/Icon'
import { MenuButton } from '../components/Menu'
import { usePdfActions } from '../lib/actions'
import { baseName, FILTERS, formatBytes, samePath, withExt } from '../lib/files'
import { call, EngineError, useServices } from '../lib/services'
import { COLORS, newId, toEngine, type Edit, type PageSpec, type Style, type TextLine, type Tool } from './pdf/model'
import { PageCanvas } from './pdf/PageCanvas'
import { SignaturePad, type Signature } from './pdf/SignaturePad'
import './pdf/pdf.css'

interface PdfInfo {
  path: string
  name: string
  bytes: number
  pages: number
  encrypted: boolean
  page_sizes: [number, number][]
  metadata: Record<string, string | null>
}

interface SignatureInfo {
  field: string
  signer: string
  signed_at: string | null
  ok: boolean
  covers_whole_file: boolean
  reason: string | null
}

interface OpenPdf {
  info: PdfInfo
  signatures: SignatureInfo[]
  /** Held in memory only, for as long as the file is open. */
  password?: string
}

/** Everything undo/redo restores. */
interface Draft {
  pages: PageSpec[]
  edits: Edit[]
}

const TOOLS: { id: Tool; icon: IconName; label: string }[] = [
  { id: 'select', icon: 'cursor', label: 'Select' },
  { id: 'edittext', icon: 'text', label: 'Edit text' },
  { id: 'text', icon: 'type', label: 'Text' },
  { id: 'highlight', icon: 'highlighter', label: 'Highlight' },
  { id: 'ink', icon: 'pen', label: 'Draw' },
  { id: 'rect', icon: 'square', label: 'Rectangle' },
  { id: 'ellipse', icon: 'circle', label: 'Ellipse' },
  { id: 'line', icon: 'line', label: 'Line' },
  { id: 'arrow', icon: 'arrow', label: 'Arrow' },
  { id: 'note', icon: 'note', label: 'Note' },
  { id: 'redact', icon: 'redact', label: 'Redact' }
]

const initialPages = (count: number): PageSpec[] => Array.from({ length: count }, (_, i) => ({ key: `p${i}`, source: i, rotate: 0 }))

export function PdfStudio(): ReactNode {
  const { ask, notify, run } = useServices()
  const actions = usePdfActions()
  const root = useRef<HTMLDivElement>(null)
  const [doc, setDoc] = useState<OpenPdf | null>(null)
  const [draft, setDraft] = useState<Draft>({ pages: [], edits: [] })
  const history = useRef<{ past: Draft[]; future: Draft[] }>({ past: [], future: [] })
  const [, bump] = useState(0)
  const [current, setCurrent] = useState(0) // index into draft.pages
  const [tool, setTool] = useState<Tool>('select')
  const [style, setStyle] = useState<Style>({ color: '#d92d20', width: 2, size: 14 })
  const [selected, setSelected] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [signing, setSigning] = useState(false)
  /** Existing text per source page, fetched the first time the Edit text tool is used on it. */
  const [lines, setLines] = useState<Record<number, TextLine[]>>({})

  const path = doc?.info.path ?? ''
  const pw = doc?.password
  const none = !doc
  const page = draft.pages[Math.min(current, draft.pages.length - 1)]
  const dirty =
    !!doc &&
    (draft.edits.length > 0 ||
      draft.pages.length !== doc.info.pages ||
      draft.pages.some((p, i) => p.source !== i || p.rotate !== 0))

  /** Replace the draft, remembering the previous one for undo. */
  const change = useCallback((next: (d: Draft) => Draft) => {
    setDraft((d) => {
      history.current.past.push(d)
      if (history.current.past.length > 100) history.current.past.shift()
      history.current.future = []
      return next(d)
    })
  }, [])

  const undo = useCallback(() => {
    const prev = history.current.past.pop()
    if (!prev) return
    setDraft((d) => {
      history.current.future.push(d)
      return prev
    })
    setSelected(null)
  }, [])

  const redo = useCallback(() => {
    const next = history.current.future.pop()
    if (!next) return
    setDraft((d) => {
      history.current.past.push(d)
      return next
    })
    setSelected(null)
  }, [])

  const removeEdit = useCallback(
    (id: string) => {
      change((d) => ({ ...d, edits: d.edits.filter((e) => e.id !== id) }))
      setSelected(null)
    },
    [change]
  )

  async function load(file: string): Promise<void> {
    let password: string | undefined
    for (;;) {
      try {
        const info = await call<PdfInfo>('pdf.info', { input: file, password })
        // A file whose signatures cannot be read still opens; it just shows none.
        const signed = await call<{ signatures: SignatureInfo[] }>('pdf.signatures', { input: file, password }).catch(() => ({ signatures: [] }))
        setDoc({ info, password, signatures: signed.signatures })
        setDraft({ pages: initialPages(info.pages), edits: [] })
        history.current = { past: [], future: [] }
        setLines({})
        setCurrent(0)
        setSelected(null)
        // Start in Edit text: clicking the words on a page is the first thing people try.
        setTool('edittext')
        return
      } catch (err) {
        if (!(err instanceof EngineError) || err.code !== 'password_required') {
          return notify('Open PDF', err instanceof Error ? err.message : String(err), 'error')
        }
        const answer = await ask({
          title: 'Password required',
          body: password === undefined ? 'This PDF is protected. Enter its password to open it.' : 'That password did not work. Try again.',
          fields: [{ name: 'pw', label: 'Password', type: 'password' }],
          confirm: 'Open'
        })
        if (!answer) return
        password = answer.pw
      }
    }
  }

  async function open(): Promise<void> {
    if (dirty && !(await confirmDiscard())) return
    const [file] = await window.suite.openFiles({ title: 'Open PDF', filters: FILTERS.pdf })
    if (file) await load(file)
  }

  async function confirmDiscard(): Promise<boolean> {
    const answer = await ask({
      title: 'Discard unsaved changes?',
      body: 'Your page changes and annotations on this PDF have not been saved.',
      fields: [],
      confirm: 'Discard'
    })
    return answer !== null
  }

  async function save(): Promise<void> {
    if (!doc) return
    const output = await window.suite.saveFile({
      title: 'Save edited PDF as',
      defaultPath: withExt(path, 'pdf', '-edited'),
      filters: FILTERS.pdf
    })
    if (!output) return
    if (samePath(path, output)) return notify('Save PDF', 'Choose a new file name so the original stays untouched.', 'error')
    const result = await run(`Save ${baseName(output)}`, 'pdf.apply_edits', {
      input: path,
      output,
      password: pw,
      pages: draft.pages.map((p) => ({ source: p.source, rotate: p.rotate })),
      edits: draft.edits.map(toEngine)
    })
    // Continue on the saved file: its pages are now in the new order with the edits baked in.
    if (result) await load(output)
  }

  /** Conversions read the file on disk, so unsaved edits would silently be left out. */
  function onSaved(action: (input: string, password?: string) => Promise<void>): () => void {
    return () => {
      if (dirty) notify('Unsaved changes', 'Save the edited PDF first; this action works on the saved file.', 'error')
      else void action(path, pw)
    }
  }

  // ---- page organiser
  function movePage(from: number, to: number): void {
    if (to < 0 || to >= draft.pages.length || from === to) return
    change((d) => {
      const pages = [...d.pages]
      pages.splice(to, 0, ...pages.splice(from, 1))
      return { ...d, pages }
    })
    setCurrent(to)
  }

  function rotatePage(index: number): void {
    change((d) => ({ ...d, pages: d.pages.map((p, i) => (i === index ? { ...p, rotate: (p.rotate + 90) % 360 } : p)) }))
  }

  function deletePage(index: number): void {
    if (draft.pages.length <= 1) return notify('Delete page', 'A PDF must keep at least one page.', 'error')
    change((d) => ({ ...d, pages: d.pages.filter((_, i) => i !== index) }))
    setCurrent((c) => Math.max(0, c > index || c >= draft.pages.length - 1 ? c - 1 : c))
    setSelected(null)
  }

  // ---- stamps that are not drawn with the pointer
  function placeImage(data_url: string, width: number, height: number, maxWidth: number): void {
    if (!doc || !page) return
    const [W, H] = doc.info.page_sizes[page.source] ?? [595, 842]
    const w = Math.min(maxWidth, W * 0.6)
    const h = (w * height) / width
    const edit: Edit = { id: newId(), page: page.source, type: 'image', x: (W - w) / 2, y: (H - h) / 2, w, h, data_url }
    change((d) => ({ ...d, edits: [...d.edits, edit] }))
    setTool('select')
    setSelected(edit.id)
  }

  async function insertImage(): Promise<void> {
    const [file] = await window.suite.openFiles({ title: 'Choose an image to place on the page', filters: FILTERS.images })
    if (!file) return
    try {
      const img = await call<{ data_url: string; width: number; height: number }>('pdf.image_data_url', { input: file })
      placeImage(img.data_url, img.width, img.height, 240)
    } catch (err) {
      notify('Insert image', err instanceof Error ? err.message : String(err), 'error')
    }
  }

  function onSignature(signature: Signature | null): void {
    setSigning(false)
    if (signature) placeImage(signature.data_url, signature.width, signature.height, 170)
  }

  async function addNote(x: number, y: number): Promise<void> {
    if (!page) return
    const answer = await ask({ title: 'Add note', fields: [{ name: 'text', label: 'Note text' }], confirm: 'Add' })
    if (!answer) return
    const source = page.source
    change((d) => ({ ...d, edits: [...d.edits, { id: newId(), page: source, type: 'note', x, y, text: answer.text }] }))
  }

  function applyStyle(patch: Partial<Style>): void {
    setStyle((s) => ({ ...s, ...patch }))
    const edit = draft.edits.find((e) => e.id === selected)
    if (!edit) return
    // Restyle the selection too, where the property applies to it.
    change((d) => ({
      ...d,
      edits: d.edits.map((e) => {
        if (e.id !== edit.id || e.type === 'image' || e.type === 'note') return e
        if (e.type === 'text') return { ...e, color: patch.color ?? e.color, size: patch.size ?? e.size }
        return { ...e, color: patch.color ?? e.color, width: patch.width ?? e.width }
      })
    }))
  }

  // The Edit text tool needs to know where the page's own text is.
  const source = page?.source
  useEffect(() => {
    if (tool !== 'edittext' || !path || source === undefined || lines[source]) return
    let cancelled = false
    call<{ editable: boolean; reason?: string; lines: TextLine[] }>('pdf.text_lines', { input: path, page: source, password: pw })
      .then((result) => {
        if (cancelled) return
        setLines((all) => ({ ...all, [source]: result.lines }))
        if (!result.editable) notify('Edit text', result.reason ?? 'The text on this page cannot be edited.', 'error')
        else if (result.lines.length === 0) notify('Edit text', 'No editable text on this page. A scanned page is a picture and needs OCR first.', 'error')
      })
      .catch((err: Error) => !cancelled && notify('Edit text', err.message, 'error'))
    return () => {
      cancelled = true
    }
  }, [tool, path, source, pw, lines, notify])

  // Keyboard shortcuts, only while this workspace is the visible one and focus is not in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (!root.current || root.current.offsetParent === null) return
      const target = e.target as HTMLElement
      if (target.closest('input, textarea, select, [contenteditable="true"], .dialog')) return
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        if (e.shiftKey) redo()
        else undo()
      } else if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        redo()
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && selected) {
        e.preventDefault()
        removeEdit(selected)
      } else if (e.key === 'Escape') {
        setTool('select')
        setSelected(null)
      }
      bump((n) => n + 1) // history lengths drive the undo/redo buttons
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, undo, redo, removeEdit])

  const pageEdits = page ? draft.edits.filter((e) => e.page === page.source) : []
  const selectedEdit = draft.edits.find((e) => e.id === selected) ?? null
  const pageSize = page ? (doc?.info.page_sizes[page.source] ?? [595, 842]) : [595, 842]
  const redactions = draft.edits.filter((e) => e.type === 'redact').length

  return (
    <div className="pdf-root" ref={root}>
      <ModuleFrame
        title="PDF Studio"
        file={doc?.info.path}
        dirty={dirty}
        notice={
          [
            redactions > 0 &&
              'Redaction is permanent once saved: each page with a redaction box is turned into an image, so its text can no longer be selected or searched. Bookmarks and document metadata are not scrubbed.',
            dirty && doc && doc.signatures.length > 0 && 'This PDF is digitally signed. Saving your edits creates a new, unsigned copy; the original stays signed.'
          ]
            .filter(Boolean)
            .join(' ') || undefined
        }
        toolbar={
          <>
            <ToolButton icon="open" label="Open" primary={none} onClick={() => void open()} />
            <ToolButton icon="save" label="Save as…" primary={dirty} disabled={!dirty} onClick={() => void save()} />
            <span className="sep" />
            <MenuButton
              icon="layers"
              label="Convert"
              disabled={none}
              items={[
                { icon: 'word', label: 'To Word (.docx)', onSelect: onSaved(actions.toWord) },
                { icon: 'table', label: 'To Excel (.xlsx)', onSelect: onSaved(actions.toExcel) },
                { icon: 'code', label: 'To HTML', onSelect: onSaved(actions.toHtml) },
                { icon: 'text', label: 'To Markdown', onSelect: onSaved(actions.toMarkdown) },
                { icon: 'text', label: 'To plain text', onSelect: onSaved(actions.toText) },
                { icon: 'image', label: 'To images (PNG)', onSelect: onSaved(actions.toImages) }
              ]}
            />
            <ToolButton icon="split" label="Split" disabled={none} onClick={onSaved(actions.split)} />
            <ToolButton icon="merge" label="Merge…" onClick={() => void actions.merge()} />
            <span className="sep" />
            <ToolButton icon="stamp" label="Watermark" disabled={none} onClick={onSaved(actions.watermark)} />
            <ToolButton icon="lock" label="Protect" disabled={none} onClick={onSaved(actions.protect)} />
            <ToolButton
              icon="signature"
              label="Sign"
              disabled={none}
              onClick={onSaved(async (input, password) => {
                const signed = await actions.sign(input, password, page ? page.source : 0)
                if (signed) await load(signed)
              })}
            />
          </>
        }
      >
        {!doc || !page ? (
          <EmptyState
            icon="pdf"
            title="Open a PDF to get started"
            body="Edit the text on a page, reorder and rotate pages, add highlights, drawings, images and signatures, redact, and convert to Word, Excel, HTML or images."
          >
            <ToolButton icon="open" label="Open PDF" primary onClick={() => void open()} />
            <ToolButton icon="merge" label="Merge PDFs" onClick={() => void actions.merge()} />
          </EmptyState>
        ) : (
          <div className="pdf-work">
            <div className="pdf-tools" role="toolbar" aria-label="Editing tools">
              {TOOLS.map((t) => (
                <button
                  key={t.id}
                  className={`tool${tool === t.id ? ' active' : ''}`}
                  title={t.label}
                  aria-label={t.label}
                  aria-pressed={tool === t.id}
                  onClick={() => {
                    setTool(t.id)
                    setSelected(null)
                  }}
                >
                  <Icon name={t.icon} size={17} />
                </button>
              ))}
              <span className="sep" />
              <button className="tool wide" onClick={() => setSigning(true)}>
                <Icon name="signature" size={17} /> Signature
              </button>
              <button className="tool wide" onClick={() => void insertImage()}>
                <Icon name="image" size={17} /> Image
              </button>
              <span className="sep" />
              <div className="swatches" role="group" aria-label="Colour">
                {COLORS.map((c) => (
                  <button
                    key={c}
                    className={`swatch${style.color === c ? ' active' : ''}`}
                    style={{ background: c }}
                    aria-label={`Colour ${c}`}
                    aria-pressed={style.color === c}
                    onClick={() => applyStyle({ color: c })}
                  />
                ))}
              </div>
              <label className="mini">
                Line
                <select aria-label="Line width" value={style.width} onChange={(e) => applyStyle({ width: Number(e.target.value) })}>
                  {[1, 2, 3, 5, 8].map((w) => (
                    <option key={w} value={w}>
                      {w} pt
                    </option>
                  ))}
                </select>
              </label>
              <label className="mini">
                Text
                <select aria-label="Text size" value={style.size} onChange={(e) => applyStyle({ size: Number(e.target.value) })}>
                  {[9, 10, 12, 14, 18, 24, 36].map((s) => (
                    <option key={s} value={s}>
                      {s} pt
                    </option>
                  ))}
                </select>
              </label>
              <span className="spacer" />
              <button className="tool" title="Undo (Ctrl+Z)" aria-label="Undo" disabled={history.current.past.length === 0} onClick={undo}>
                <Icon name="undo" size={17} />
              </button>
              <button className="tool" title="Redo (Ctrl+Y)" aria-label="Redo" disabled={history.current.future.length === 0} onClick={redo}>
                <Icon name="redo" size={17} />
              </button>
              <span className="sep" />
              <button className="tool" title="Zoom out" aria-label="Zoom out" disabled={zoom <= 0.5} onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}>
                <Icon name="zoomOut" size={17} />
              </button>
              <span className="zoom-label">{Math.round(zoom * 100)}%</span>
              <button className="tool" title="Zoom in" aria-label="Zoom in" disabled={zoom >= 3} onClick={() => setZoom((z) => Math.min(3, z + 0.25))}>
                <Icon name="zoomIn" size={17} />
              </button>
            </div>

            <div className="pdf-layout">
              <div className="pdf-thumbs" aria-label="Pages">
                {draft.pages.map((p, i) => (
                  <PageThumb
                    key={p.key}
                    path={path}
                    password={pw}
                    spec={p}
                    index={i}
                    count={draft.pages.length}
                    selected={i === current}
                    marks={draft.edits.filter((e) => e.page === p.source).length}
                    onSelect={() => {
                      setCurrent(i)
                      setSelected(null)
                    }}
                    onMove={movePage}
                    onRotate={() => rotatePage(i)}
                    onDelete={() => deletePage(i)}
                  />
                ))}
              </div>

              <PageCanvas
                path={path}
                password={pw}
                source={page.source}
                size={pageSize as [number, number]}
                rotate={page.rotate}
                zoom={zoom}
                edits={pageEdits}
                lines={tool === 'edittext' ? (lines[page.source] ?? []) : []}
                tool={tool}
                style={style}
                selected={selected}
                onSelect={setSelected}
                onAdd={(edit) => {
                  change((d) => ({ ...d, edits: [...d.edits, edit] }))
                  // After adding new text, switch to Select so it can be moved; stay put while editing existing text.
                  if (edit.type === 'text' && !edit.replaces) {
                    setTool('select')
                    setSelected(edit.id)
                  }
                }}
                onChange={(edit) => change((d) => ({ ...d, edits: d.edits.map((e) => (e.id === edit.id ? edit : e)) }))}
                onRemove={removeEdit}
                onNote={(x, y) => void addNote(x, y)}
              />

              <aside className="inspector">
                <h3>Document</h3>
                <dl>
                  <dt>Pages</dt>
                  <dd>
                    {draft.pages.length}
                    {draft.pages.length !== doc.info.pages && ` (was ${doc.info.pages})`}
                  </dd>
                  <dt>Size</dt>
                  <dd>{formatBytes(doc.info.bytes)}</dd>
                  <dt>Page size</dt>
                  <dd>
                    {pageSize[0]} × {pageSize[1]} pt
                  </dd>
                  <dt>Encrypted</dt>
                  <dd>{doc.info.encrypted ? 'Yes' : 'No'}</dd>
                  <dt>Annotations</dt>
                  <dd>{draft.edits.length}</dd>
                </dl>

                <h3>
                  Page {current + 1} of {draft.pages.length}
                </h3>
                <div className="pager">
                  <button className="btn" disabled={current === 0} onClick={() => setCurrent(current - 1)}>
                    Previous
                  </button>
                  <button className="btn" disabled={current >= draft.pages.length - 1} onClick={() => setCurrent(current + 1)}>
                    Next
                  </button>
                </div>

                {tool === 'edittext' && (
                  <>
                    <h3 className="gap">Edit text</h3>
                    <p className="muted small">
                      Click any line of text on the page to change it. Clear the text to delete the line. Press Ctrl+Enter or click
                      away to finish; Esc cancels. The change is written when you save.
                    </p>
                  </>
                )}

                {doc.signatures.length > 0 && (
                  <>
                    <h3 className="gap">Digital signatures</h3>
                    <ul className="pdf-sigs">
                      {doc.signatures.map((sig) => (
                        <li key={sig.field} className={sig.ok ? 'ok' : 'bad'}>
                          <Icon name={sig.ok ? 'check' : 'alert'} size={15} />
                          <span>
                            <strong>{sig.signer}</strong>
                            <small>
                              {sig.ok
                                ? sig.covers_whole_file
                                  ? 'Unchanged since signing'
                                  : 'Valid; changes were added after it'
                                : 'Document changed after signing, or signature damaged'}
                              {sig.signed_at && ` · ${new Date(sig.signed_at).toLocaleString()}`}
                              {sig.reason && ` · ${sig.reason}`}
                            </small>
                          </span>
                        </li>
                      ))}
                    </ul>
                    <p className="muted small">
                      Checked for integrity only. Whether the signer&apos;s certificate is trusted or revoked is not verified offline.
                    </p>
                  </>
                )}

                {selectedEdit && (
                  <>
                    <h3 className="gap">Selection</h3>
                    <p className="muted small">
                      {selectedEdit.type === 'text'
                        ? 'Double-click the text to edit it. Drag to move.'
                        : 'Drag to move. Use the corner handle to resize boxes and images.'}
                    </p>
                    <button className="btn" onClick={() => removeEdit(selectedEdit.id)}>
                      <Icon name="trash" size={16} /> Delete
                    </button>
                  </>
                )}
              </aside>
            </div>
          </div>
        )}
      </ModuleFrame>
      {signing && <SignaturePad onClose={onSignature} />}
    </div>
  )
}

/** One page in the organiser. Renders its thumbnail only once scrolled into view. */
function PageThumb(props: {
  path: string
  password?: string
  spec: PageSpec
  index: number
  count: number
  selected: boolean
  marks: number
  onSelect(): void
  onMove(from: number, to: number): void
  onRotate(): void
  onDelete(): void
}): ReactNode {
  const ref = useRef<HTMLDivElement>(null)
  const [src, setSrc] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const { path, password, spec, index } = props

  useEffect(() => {
    const el = ref.current
    if (!el) return
    let cancelled = false
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        observer.disconnect()
        call<{ data_url: string }>('pdf.render_page', { input: path, page: spec.source, width: 220, password })
          .then((r) => !cancelled && setSrc(r.data_url))
          .catch(() => undefined)
      },
      { rootMargin: '300px' }
    )
    observer.observe(el)
    return () => {
      cancelled = true
      observer.disconnect()
    }
  }, [path, spec.source, password])

  useEffect(() => {
    if (props.selected) ref.current?.scrollIntoView({ block: 'nearest' })
  }, [props.selected])

  return (
    <div
      ref={ref}
      className={`pdf-thumb${props.selected ? ' selected' : ''}${over ? ' drop' : ''}`}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', String(index))
        e.dataTransfer.effectAllowed = 'move'
      }}
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        const from = Number(e.dataTransfer.getData('text/plain'))
        if (Number.isInteger(from)) props.onMove(from, index)
      }}
    >
      <button className="pdf-thumb-page" aria-label={`Page ${index + 1}`} aria-pressed={props.selected} onClick={props.onSelect}>
        {src && <img src={src} alt="" draggable={false} style={{ transform: `rotate(${spec.rotate}deg)` }} />}
        {props.marks > 0 && <span className="pdf-thumb-marks">{props.marks}</span>}
      </button>
      <div className="pdf-thumb-bar">
        <span className="pdf-thumb-num">{index + 1}</span>
        <button title="Move up" aria-label={`Move page ${index + 1} up`} disabled={index === 0} onClick={() => props.onMove(index, index - 1)}>
          <Icon name="up" size={13} />
        </button>
        <button title="Move down" aria-label={`Move page ${index + 1} down`} disabled={index === props.count - 1} onClick={() => props.onMove(index, index + 1)}>
          <Icon name="down" size={13} />
        </button>
        <button title="Rotate" aria-label={`Rotate page ${index + 1}`} onClick={props.onRotate}>
          <Icon name="rotate" size={13} />
        </button>
        <button title="Delete page" aria-label={`Delete page ${index + 1}`} disabled={props.count <= 1} onClick={props.onDelete}>
          <Icon name="trash" size={13} />
        </button>
      </div>
    </div>
  )
}
