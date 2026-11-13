// Everything that touches the Univer spreadsheet library lives here, so the
// rest of the module only sees a small, stable surface.
import { UniverSheetsConditionalFormattingPreset } from '@univerjs/preset-sheets-conditional-formatting'
import cfEnUS from '@univerjs/preset-sheets-conditional-formatting/locales/en-US'
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core'
import coreEnUS from '@univerjs/preset-sheets-core/locales/en-US'
import { UniverSheetsDataValidationPreset } from '@univerjs/preset-sheets-data-validation'
import dvEnUS from '@univerjs/preset-sheets-data-validation/locales/en-US'
import { UniverSheetsFilterPreset } from '@univerjs/preset-sheets-filter'
import filterEnUS from '@univerjs/preset-sheets-filter/locales/en-US'
import { UniverSheetsFindReplacePreset } from '@univerjs/preset-sheets-find-replace'
import findEnUS from '@univerjs/preset-sheets-find-replace/locales/en-US'
import { UniverSheetsSortPreset } from '@univerjs/preset-sheets-sort'
import sortEnUS from '@univerjs/preset-sheets-sort/locales/en-US'
import { CommandType, createUniver, LocaleType, mergeLocales, type IWorkbookData } from '@univerjs/presets'

import '@univerjs/preset-sheets-core/lib/index.css'
import '@univerjs/preset-sheets-filter/lib/index.css'
import '@univerjs/preset-sheets-sort/lib/index.css'
import '@univerjs/preset-sheets-find-replace/lib/index.css'
import '@univerjs/preset-sheets-conditional-formatting/lib/index.css'
import '@univerjs/preset-sheets-data-validation/lib/index.css'

export type Snapshot = Partial<IWorkbookData>

export interface CellRange {
  startRow: number
  endRow: number
  startColumn: number
  endColumn: number
}

export interface SheetSelection {
  sheetId: string
  sheetName: string
  range: CellRange
  a1: string
}

export interface Grid {
  /** Replace the open workbook. */
  load(snapshot: Snapshot): void
  /** The whole workbook as it stands, including computed formula values. */
  snapshot(): Snapshot | null
  /** The selected range, widened to the sheet's used range when only one cell is selected. */
  selection(): SheetSelection | null
  /** Displayed text of a range on a sheet (what the user sees, after formatting). */
  values(sheetId: string, range: CellRange): string[][]
  /** Called after every change that alters the saved document. */
  onChange(listener: () => void): () => void
  dispose(): void
}

let unitSeq = 0

export function createGrid(container: HTMLElement): Grid {
  const dark = window.matchMedia('(prefers-color-scheme: dark)')
  const { univer, univerAPI } = createUniver({
    locale: LocaleType.EN_US,
    locales: { [LocaleType.EN_US]: mergeLocales(coreEnUS, filterEnUS, sortEnUS, findEnUS, cfEnUS, dvEnUS) },
    darkMode: dark.matches,
    presets: [
      UniverSheetsCorePreset({ container }),
      UniverSheetsFilterPreset(),
      UniverSheetsSortPreset(),
      UniverSheetsFindReplacePreset(),
      UniverSheetsConditionalFormattingPreset(),
      UniverSheetsDataValidationPreset()
    ]
  })
  const followTheme = (e: MediaQueryListEvent): void => univerAPI.toggleDarkMode(e.matches)
  dark.addEventListener('change', followTheme)

  const listeners = new Set<() => void>()
  let unitId: string | null = null
  let watching: { dispose(): void } | null = null
  // Loading a workbook fires mutations of its own (first formula pass, layout);
  // only changes after that count as the user's edits.
  let settled = false

  return {
    load(snapshot) {
      watching?.dispose()
      if (unitId) univerAPI.disposeUnit(unitId)
      settled = false
      unitId = `workbook-${++unitSeq}`
      const workbook = univerAPI.createWorkbook({ ...snapshot, id: unitId })
      watching = workbook.onCommandExecuted((command) => {
        if (!settled || command.type !== CommandType.MUTATION) return
        // Recalculation results are derived data, not an edit.
        if (command.id.startsWith('formula.')) return
        listeners.forEach((fn) => fn())
      })
      window.setTimeout(() => (settled = true), 600)
    },

    snapshot() {
      return univerAPI.getActiveWorkbook()?.save() ?? null
    },

    selection() {
      const sheet = univerAPI.getActiveWorkbook()?.getActiveSheet()
      if (!sheet) return null
      let range = sheet.getSelection()?.getActiveRange() ?? null
      const r = range?.getRange()
      if (!range || !r || (r.startRow === r.endRow && r.startColumn === r.endColumn)) range = sheet.getDataRange()
      const box = range.getRange()
      return {
        sheetId: sheet.getSheetId(),
        sheetName: sheet.getSheetName(),
        range: { startRow: box.startRow, endRow: box.endRow, startColumn: box.startColumn, endColumn: box.endColumn },
        a1: range.getA1Notation()
      }
    },

    values(sheetId, range) {
      const sheet = univerAPI
        .getActiveWorkbook()
        ?.getSheets()
        .find((s) => s.getSheetId() === sheetId)
      if (!sheet) return []
      return sheet
        .getRange(range.startRow, range.startColumn, range.endRow - range.startRow + 1, range.endColumn - range.startColumn + 1)
        .getDisplayValues()
    },

    onChange(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },

    dispose() {
      dark.removeEventListener('change', followTheme)
      watching?.dispose()
      listeners.clear()
      univer.dispose()
    }
  }
}

export function blankWorkbook(): Snapshot {
  return {
    name: 'Workbook',
    sheetOrder: ['sheet-1'],
    styles: {},
    sheets: { 'sheet-1': { id: 'sheet-1', name: 'Sheet1', rowCount: 200, columnCount: 26, cellData: {} } }
  }
}
