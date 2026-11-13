import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { EmptyState, ModuleFrame, ToolButton } from '../components/Frame'
import type { FileFilter } from '../../../shared/api'
import { baseName, FILTERS, samePath, withExt } from '../lib/files'
import { useServices } from '../lib/services'
import { ChartPanel, type ChartSpec, type ChartType } from './sheets/ChartPanel'
import { blankWorkbook, createGrid, type Grid, type Snapshot } from './sheets/univer'
import './sheets/sheets.css'

const OPEN_FILTERS: FileFilter[] = [{ name: 'Spreadsheets', extensions: ['xlsx', 'xlsm', 'xls', 'csv', 'tsv'] }]
const SAVE_FILTERS: FileFilter[] = [
  { name: 'Excel workbook', extensions: ['xlsx'] },
  { name: 'CSV (first sheet, values only)', extensions: ['csv'] },
  { name: 'Tab-separated values', extensions: ['tsv'] }
]

interface Book {
  path: string | null
  /** Opened from a file this app did not write: saving over it could drop content we did not import. */
  foreign: boolean
  /** Only part of the file was loaded; saving is disabled so rows are never silently lost. */
  truncated: boolean
  /** What the engine could not import (charts, images, …). */
  notes: string[]
}

interface OpenResult {
  workbook: Snapshot
  notes: string[]
  truncated: boolean
}

let chartSeq = 0

export function Sheets(): ReactNode {
  const { run, notify } = useServices()
  const host = useRef<HTMLDivElement>(null)
  const grid = useRef<Grid | null>(null)
  const [book, setBook] = useState<Book | null>(null)
  const [dirty, setDirty] = useState(false)
  const [charts, setCharts] = useState<ChartSpec[]>([])
  const [showCharts, setShowCharts] = useState(false)
  const [revision, setRevision] = useState(0)

  // The grid is created on first use (it is the heaviest part of the app) and kept for the session.
  const ensureGrid = useCallback((): Grid | null => {
    if (!grid.current && host.current) {
      grid.current = createGrid(host.current)
      grid.current.onChange(() => {
        setDirty(true)
        setRevision((n) => n + 1)
      })
    }
    return grid.current
  }, [])

  useEffect(
    () => () => {
      grid.current?.dispose()
      grid.current = null
    },
    []
  )

  function show(snapshot: Snapshot, next: Book): void {
    const g = ensureGrid()
    if (!g) return
    g.load(snapshot)
    setBook(next)
    setCharts([])
    setDirty(false)
  }

  function newBook(): void {
    show(blankWorkbook(), { path: null, foreign: false, truncated: false, notes: [] })
  }

  async function open(): Promise<void> {
    const [path] = await window.suite.openFiles({ title: 'Open spreadsheet', filters: OPEN_FILTERS })
    if (!path) return
    const result = await run<OpenResult>(`Open ${baseName(path)}`, 'sheet.open', { input: path })
    if (!result) return
    show(result.workbook, { path, foreign: true, truncated: result.truncated, notes: result.notes })
  }

  async function saveAs(): Promise<void> {
    const snapshot = grid.current?.snapshot()
    if (!book || !snapshot) return
    if (book.truncated) {
      return notify('Save spreadsheet', 'This file was only partly loaded, so saving is disabled to avoid losing rows.', 'error')
    }
    const output = await window.suite.saveFile({
      title: 'Save spreadsheet as',
      defaultPath: book.path ? withExt(book.path, 'xlsx', book.foreign ? '-edited' : '') : 'Workbook.xlsx',
      filters: SAVE_FILTERS
    })
    if (!output) return
    if (book.foreign && book.path && samePath(book.path, output)) {
      return notify('Save spreadsheet', 'Choose a new name so the original file, and anything in it this editor did not import, is kept.', 'error')
    }
    const isXlsx = /\.xlsx$/i.test(output)
    const result = await run(`Save ${baseName(output)}`, 'sheet.save', {
      output,
      workbook: snapshot,
      charts: isXlsx ? charts.map((c) => ({ sheet: c.sheetId, type: c.type, title: c.title, range: c.range })) : []
    })
    if (!result) return
    if (isXlsx) {
      // The xlsx now holds everything on screen, so it becomes the document.
      setBook({ ...book, path: output, foreign: false, notes: [] })
      setDirty(false)
    }
  }

  async function exportPdf(): Promise<void> {
    if (!book?.path || dirty || !/\.(xlsx|csv)$/i.test(book.path)) {
      return notify('Export PDF', 'Save the workbook as .xlsx first, then export it.', 'error')
    }
    const output = await window.suite.saveFile({ title: 'Export PDF as', defaultPath: withExt(book.path, 'pdf'), filters: FILTERS.pdf })
    if (output) await run(`${baseName(book.path)} → PDF`, 'convert.run', { input: book.path, output })
  }

  function addChart(type: ChartType): void {
    const selection = grid.current?.selection()
    if (!selection) return
    const { range } = selection
    if (range.endRow - range.startRow < 1 || range.endColumn - range.startColumn < 1) {
      return notify('Add chart', 'Select at least two rows and two columns: a header row, a label column and values.', 'error')
    }
    setCharts((list) => [...list, { id: `chart-${++chartSeq}`, type, title: '', ...selection }])
    setDirty(true)
  }

  const notes = book
    ? [
        ...book.notes,
        ...(charts.length > 0 ? ['Charts are written into the .xlsx for Excel, but are not read back when a file is opened here'] : [])
      ]
    : []

  return (
    <ModuleFrame
      title="Spreadsheets"
      file={book ? (book.path ?? 'Untitled workbook') : null}
      dirty={dirty}
      notice={notes.length > 0 && notes.join(' · ')}
      toolbar={
        <>
          <ToolButton icon="plus" label="New" onClick={newBook} />
          <ToolButton icon="open" label="Open" primary={!book} onClick={() => void open()} />
          <ToolButton icon="save" label="Save as…" primary={!!book && dirty} disabled={!book} onClick={() => void saveAs()} />
          <span className="sep" />
          <ToolButton icon="layers" label="Charts" disabled={!book} onClick={() => setShowCharts((v) => !v)} />
          <ToolButton icon="pdf" label="Export PDF" disabled={!book} onClick={() => void exportPdf()} />
        </>
      }
    >
      <div className="sheets-body">
        {/* Univer owns this element; it stays mounted so the grid survives switching workspaces. */}
        <div className="sheets-grid" ref={host} hidden={!book} />
        {!book && (
          <EmptyState
            icon="sheet"
            title="Open or create a workbook"
            body="A full grid with live formulas, formatting, merged cells, freeze panes, sort, filter, find and replace, conditional formatting, data validation and charts."
          >
            <ToolButton icon="open" label="Open spreadsheet" primary onClick={() => void open()} />
            <ToolButton icon="plus" label="New workbook" onClick={newBook} />
          </EmptyState>
        )}
        {book && showCharts && (
          <ChartPanel
            // `revision` changes whenever cells change, re-rendering the previews with fresh values.
            data-revision={revision}
            charts={charts}
            rowsFor={(spec) => grid.current?.values(spec.sheetId, spec.range) ?? []}
            onAdd={addChart}
            onChange={(spec) => {
              setCharts((list) => list.map((c) => (c.id === spec.id ? spec : c)))
              setDirty(true)
            }}
            onRemove={(id) => {
              setCharts((list) => list.filter((c) => c.id !== id))
              setDirty(true)
            }}
            onClose={() => setShowCharts(false)}
          />
        )}
      </div>
    </ModuleFrame>
  )
}
