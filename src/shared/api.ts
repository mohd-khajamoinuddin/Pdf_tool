// The contract between the sandboxed renderer and the main process.
// The renderer sees exactly this surface (window.suite) and nothing else.

export interface FileFilter {
  name: string
  extensions: string[]
}

export interface EngineFailure {
  code: string
  message: string
}

export type EngineReply<T = unknown> = { ok: true; result: T } | { ok: false; error: EngineFailure }

export interface ProgressEvent {
  jobId: string
  value: number
  message: string
}

export type EngineState = 'starting' | 'ready' | 'stopped'

export interface EngineStatus {
  state: EngineState
  detail?: string
}

export interface PrintOptions {
  landscape?: boolean
  /** 'A4', 'Letter', ... or an exact size in inches. Ignored when the page sets a CSS @page size. */
  pageSize?: 'A3' | 'A4' | 'A5' | 'Letter' | 'Legal' | 'Tabloid' | { width: number; height: number }
  /** Margins in inches. Default: none (let the page's CSS decide). */
  margins?: { top?: number; bottom?: number; left?: number; right?: number }
}

export interface SuiteApi {
  /** Call a processing-engine method. `jobId` opts in to progress events. */
  engine<T = unknown>(method: string, params?: Record<string, unknown>, jobId?: string): Promise<EngineReply<T>>
  engineStatus(): Promise<EngineStatus>
  onEngineStatus(listener: (status: EngineStatus) => void): () => void
  onProgress(listener: (event: ProgressEvent) => void): () => void

  /** Native pickers. A path only becomes usable by the engine once picked here. */
  openFiles(options: { title?: string; filters?: FileFilter[]; multiple?: boolean }): Promise<string[]>
  openFolder(options?: { title?: string }): Promise<string | null>
  saveFile(options: { title?: string; defaultPath?: string; filters?: FileFilter[] }): Promise<string | null>

  /**
   * Print the current window to a PDF file (Chromium's print pipeline, so the result
   * matches the screen). Use `@media print` CSS to show only the content to export.
   * `output` must come from saveFile(). Resolves with an error message on failure.
   */
  printToPdf(output: string, options?: PrintOptions): Promise<{ ok: true } | { ok: false; message: string }>

  revealInFolder(path: string): Promise<void>
  openPath(path: string): Promise<void>
}
