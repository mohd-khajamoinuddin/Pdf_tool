import { rename, rm, writeFile } from 'node:fs/promises'
import { resolve, sep } from 'node:path'
import { BrowserWindow, dialog, ipcMain, shell } from 'electron'
import type { EngineReply, FileFilter, PrintOptions, ProgressEvent } from '../shared/api'
import { Engine, EngineCallError } from './engine'

/**
 * Least privilege for the renderer: it can only hand the engine paths the user
 * picked in a native dialog (or files the engine itself produced). A bug or
 * injected content in the UI therefore cannot read or overwrite arbitrary files.
 */
class PathGrants {
  private files = new Set<string>()
  private dirs = new Set<string>()

  private key(p: string): string {
    const full = resolve(p)
    return process.platform === 'win32' ? full.toLowerCase() : full
  }

  grantFile(p: string): void {
    this.files.add(this.key(p))
  }

  grantDir(p: string): void {
    this.dirs.add(this.key(p))
  }

  allowsDir(p: string): boolean {
    return this.dirs.has(this.key(p))
  }

  allowsFile(p: string): boolean {
    const k = this.key(p)
    if (this.files.has(k)) return true
    for (const d of this.dirs) if (k.startsWith(d.endsWith(sep) ? d : d + sep)) return true
    return false
  }
}

function checkParams(grants: PathGrants, params: Record<string, unknown>): string | null {
  const files: unknown[] = [params.input, params.output, params.certificate]
  if (params.inputs !== undefined) {
    if (!Array.isArray(params.inputs)) return 'inputs must be a list'
    files.push(...params.inputs)
  }
  for (const f of files) {
    if (f === undefined) continue
    if (typeof f !== 'string' || !grants.allowsFile(f)) return `Path was not chosen by the user: ${String(f)}`
  }
  const dir = params.output_dir
  if (dir !== undefined && (typeof dir !== 'string' || !grants.allowsDir(dir))) {
    return `Folder was not chosen by the user: ${String(dir)}`
  }
  return null
}

/** Remember files the engine wrote so the UI can reveal / open them. */
function grantOutputs(grants: PathGrants, result: unknown): void {
  if (!result || typeof result !== 'object') return
  const r = result as Record<string, unknown>
  if (typeof r.output === 'string') grants.grantFile(r.output)
  if (Array.isArray(r.files)) for (const f of r.files) if (typeof f === 'string') grants.grantFile(f)
}

export function registerIpc(engine: Engine, getWindow: () => BrowserWindow | null): void {
  const grants = new PathGrants()
  const parent = (): BrowserWindow => getWindow() as BrowserWindow

  ipcMain.handle(
    'engine:call',
    async (event, method: unknown, params: unknown, jobId: unknown): Promise<EngineReply> => {
      if (typeof method !== 'string' || (params != null && typeof params !== 'object')) {
        return { ok: false, error: { code: 'bad_request', message: 'Malformed engine call' } }
      }
      const p = (params ?? {}) as Record<string, unknown>
      const denied = checkParams(grants, p)
      if (denied) return { ok: false, error: { code: 'path_not_granted', message: denied } }

      const onProgress =
        typeof jobId === 'string'
          ? (value: number, message: string): void => {
              if (!event.sender.isDestroyed()) {
                event.sender.send('engine:progress', { jobId, value, message } satisfies ProgressEvent)
              }
            }
          : undefined
      try {
        const result = await engine.call(method, p, onProgress)
        grantOutputs(grants, result)
        return { ok: true, result }
      } catch (err) {
        const failure =
          err instanceof EngineCallError ? err.failure : { code: 'internal', message: String((err as Error)?.message ?? err) }
        return { ok: false, error: failure }
      }
    }
  )

  ipcMain.handle('engine:status', () => engine.getStatus())

  ipcMain.handle(
    'dialog:open',
    async (_e, options: { title?: string; filters?: FileFilter[]; multiple?: boolean } = {}) => {
      const res = await dialog.showOpenDialog(parent(), {
        title: options.title,
        filters: options.filters,
        properties: options.multiple ? ['openFile', 'multiSelections'] : ['openFile']
      })
      if (res.canceled) return []
      res.filePaths.forEach((p) => grants.grantFile(p))
      return res.filePaths
    }
  )

  ipcMain.handle('dialog:openFolder', async (_e, options: { title?: string } = {}) => {
    const res = await dialog.showOpenDialog(parent(), {
      title: options.title,
      properties: ['openDirectory', 'createDirectory']
    })
    if (res.canceled || !res.filePaths[0]) return null
    grants.grantDir(res.filePaths[0])
    return res.filePaths[0]
  })

  ipcMain.handle(
    'dialog:save',
    async (_e, options: { title?: string; defaultPath?: string; filters?: FileFilter[] } = {}) => {
      // The OS dialog asks before replacing an existing file.
      const res = await dialog.showSaveDialog(parent(), {
        title: options.title,
        defaultPath: options.defaultPath,
        filters: options.filters
      })
      if (res.canceled || !res.filePath) return null
      grants.grantFile(res.filePath)
      return res.filePath
    }
  )

  ipcMain.handle('window:printToPdf', async (event, output: unknown, options: PrintOptions = {}) => {
    if (typeof output !== 'string' || !grants.allowsFile(output)) {
      return { ok: false, message: 'Output path was not chosen by the user.' }
    }
    const tmp = `${output}.${process.pid}.tmp`
    try {
      const data = await event.sender.printToPDF({
        landscape: options.landscape === true,
        pageSize: options.pageSize ?? 'A4',
        printBackground: true,
        preferCSSPageSize: true,
        margins: { top: 0, bottom: 0, left: 0, right: 0, ...options.margins }
      })
      await writeFile(tmp, data)
      await rename(tmp, output)
      return { ok: true }
    } catch (err) {
      await rm(tmp, { force: true })
      return { ok: false, message: String((err as Error)?.message ?? err) }
    }
  })

  ipcMain.handle('shell:reveal', (_e, path: unknown) => {
    if (typeof path !== 'string') return
    if (grants.allowsDir(path)) void shell.openPath(path)
    else if (grants.allowsFile(path)) shell.showItemInFolder(resolve(path))
  })

  ipcMain.handle('shell:open', async (_e, path: unknown) => {
    if (typeof path === 'string' && grants.allowsFile(path)) await shell.openPath(resolve(path))
  })
}
