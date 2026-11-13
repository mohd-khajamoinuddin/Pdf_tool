import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createInterface } from 'node:readline'
import { app } from 'electron'
import type { EngineFailure, EngineStatus } from '../shared/api'

type Progress = (value: number, message: string) => void

interface Pending {
  resolve(value: unknown): void
  reject(error: EngineCallError): void
  onProgress?: Progress
}

export class EngineCallError extends Error {
  constructor(readonly failure: EngineFailure) {
    super(failure.message)
  }
}

const READY_TIMEOUT_MS = 30_000

/**
 * Owns the Python processing engine: one long-lived child process, spoken to
 * over stdin/stdout with newline-delimited JSON. No port is opened, so there
 * is nothing for another program on the machine to connect to.
 */
export class Engine {
  private proc: ChildProcessWithoutNullStreams | null = null
  private starting: Promise<void> | null = null
  private pending = new Map<number, Pending>()
  private nextId = 1
  private status: EngineStatus = { state: 'stopped' }
  private quitting = false

  constructor(private readonly onStatus: (status: EngineStatus) => void) {}

  getStatus(): EngineStatus {
    return this.status
  }

  /** Where the engine lives: a frozen binary when packaged, the venv in dev. */
  private command(): { file: string; args: string[]; cwd: string } {
    if (app.isPackaged) {
      const dir = join(process.resourcesPath, 'engine')
      const exe = process.platform === 'win32' ? 'docsuite-engine.exe' : 'docsuite-engine'
      return { file: join(dir, exe), args: [], cwd: dir }
    }
    // Development only: run a frozen engine build instead of the venv, to test packaging.
    const frozen = process.env.DOCSUITE_ENGINE
    if (frozen) return { file: frozen, args: [], cwd: dirname(frozen) }
    const cwd = join(app.getAppPath(), 'engine')
    const venv =
      process.platform === 'win32'
        ? join(cwd, '.venv', 'Scripts', 'python.exe')
        : join(cwd, '.venv', 'bin', 'python')
    const file = process.env.DOCSUITE_PYTHON || (existsSync(venv) ? venv : 'python')
    return { file, args: ['-m', 'docsuite_engine'], cwd }
  }

  private setStatus(status: EngineStatus): void {
    this.status = status
    this.onStatus(status)
  }

  start(): Promise<void> {
    if (this.proc && this.status.state === 'ready') return Promise.resolve()
    if (this.starting) return this.starting

    this.setStatus({ state: 'starting' })
    this.starting = new Promise<void>((resolve, reject) => {
      const { file, args, cwd } = this.command()
      let settled = false
      const fail = (detail: string): void => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        reject(new EngineCallError({ code: 'engine_unavailable', message: detail }))
      }
      const timer = setTimeout(() => {
        fail('The processing engine did not start in time.')
        this.proc?.kill()
      }, READY_TIMEOUT_MS)

      let proc: ChildProcessWithoutNullStreams
      try {
        proc = spawn(file, args, {
          cwd,
          windowsHide: true,
          env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1' }
        })
      } catch (err) {
        this.setStatus({ state: 'stopped', detail: String(err) })
        fail(`Could not launch the processing engine: ${String(err)}`)
        return
      }
      this.proc = proc

      createInterface({ input: proc.stdout }).on('line', (line) => {
        let msg: any
        try {
          msg = JSON.parse(line)
        } catch {
          console.warn('[engine] unparseable line:', line.slice(0, 200))
          return
        }
        if (msg.event === 'ready') {
          settled = true
          clearTimeout(timer)
          this.setStatus({ state: 'ready' })
          resolve()
          return
        }
        this.dispatch(msg)
      })
      proc.stderr.on('data', (chunk: Buffer) => console.warn('[engine]', chunk.toString().trimEnd()))
      proc.on('error', (err) => {
        this.setStatus({ state: 'stopped', detail: err.message })
        fail(`Could not launch the processing engine (${file}): ${err.message}`)
      })
      proc.on('exit', (code, signal) => {
        if (this.proc === proc) this.proc = null
        const detail = this.quitting ? undefined : `Engine exited (${signal ?? code})`
        this.setStatus({ state: 'stopped', detail })
        fail(detail ?? 'Engine stopped')
        // Anything still in flight will never be answered.
        for (const [id, p] of this.pending) {
          this.pending.delete(id)
          p.reject(new EngineCallError({ code: 'engine_crashed', message: 'The processing engine stopped unexpectedly.' }))
        }
      })
    }).finally(() => {
      this.starting = null
    })
    return this.starting
  }

  private dispatch(msg: any): void {
    const p = this.pending.get(msg.id)
    if (!p) return
    if (msg.event === 'progress') {
      p.onProgress?.(Number(msg.value) || 0, String(msg.message ?? ''))
      return
    }
    this.pending.delete(msg.id)
    if (msg.error) p.reject(new EngineCallError(msg.error))
    else p.resolve(msg.result)
  }

  /** Starts (or restarts) the engine on demand, then sends one request. */
  async call(method: string, params: Record<string, unknown> = {}, onProgress?: Progress): Promise<unknown> {
    await this.start()
    const proc = this.proc
    if (!proc) throw new EngineCallError({ code: 'engine_unavailable', message: 'The processing engine is not running.' })
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject, onProgress })
      proc.stdin.write(JSON.stringify({ id, method, params }) + '\n', (err) => {
        if (err && this.pending.delete(id)) {
          reject(new EngineCallError({ code: 'engine_unavailable', message: err.message }))
        }
      })
    })
  }

  stop(): void {
    this.quitting = true
    // Closing stdin ends the engine's read loop so it exits cleanly.
    this.proc?.stdin.end()
    const proc = this.proc
    if (proc) setTimeout(() => proc.exitCode === null && proc.kill(), 1500).unref()
  }
}
