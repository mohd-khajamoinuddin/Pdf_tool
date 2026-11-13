import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { EngineFailure, EngineStatus } from '../../../shared/api'

/** Thrown by `call` so callers can branch on `code` (e.g. password_required). */
export class EngineError extends Error {
  readonly code: string
  constructor(failure: EngineFailure) {
    super(failure.message)
    this.code = failure.code
  }
}

/** A quiet engine call: no job tray entry, throws EngineError on failure. */
export async function call<T>(method: string, params?: Record<string, unknown>, jobId?: string): Promise<T> {
  const reply = await window.suite.engine<T>(method, params, jobId)
  if (!reply.ok) throw new EngineError(reply.error)
  return reply.result
}

export interface Job {
  id: string
  label: string
  status: 'running' | 'done' | 'error'
  progress: number
  message: string
  /** File or folder produced, for "Show in folder". */
  output?: string
}

export interface PromptField {
  name: string
  label: string
  type?: 'text' | 'password' | 'checkbox'
  placeholder?: string
  hint?: string
  initial?: string
  optional?: boolean
}

interface PromptRequest {
  title: string
  body?: string
  fields: PromptField[]
  confirm?: string
  resolve(values: Record<string, string> | null): void
}

interface Services {
  engine: EngineStatus
  jobs: Job[]
  /** A user-visible engine call with progress. Resolves null on failure (already reported in the tray). */
  run<T>(label: string, method: string, params: Record<string, unknown>): Promise<T | null>
  notify(label: string, message: string, status?: 'done' | 'error'): void
  dismissJob(id: string): void
  /** In-app form dialog. Resolves null when cancelled; checkbox fields answer 'true' / 'false'. */
  ask(request: Omit<PromptRequest, 'resolve'>): Promise<Record<string, string> | null>
}

const Ctx = createContext<Services | null>(null)

export function useServices(): Services {
  const value = useContext(Ctx)
  if (!value) throw new Error('ServicesProvider is missing')
  return value
}

let jobSeq = 0

export function ServicesProvider({ children }: { children: ReactNode }): ReactNode {
  const [engine, setEngine] = useState<EngineStatus>({ state: 'starting' })
  const [jobs, setJobs] = useState<Job[]>([])
  const [prompt, setPrompt] = useState<PromptRequest | null>(null)

  const patch = useCallback((id: string, change: Partial<Job>) => {
    setJobs((list) => list.map((j) => (j.id === id ? { ...j, ...change } : j)))
  }, [])

  useEffect(() => {
    void window.suite.engineStatus().then(setEngine)
    const offStatus = window.suite.onEngineStatus(setEngine)
    const offProgress = window.suite.onProgress((e) => patch(e.jobId, { progress: e.value, message: e.message }))
    return () => {
      offStatus()
      offProgress()
    }
  }, [patch])

  const push = useCallback((job: Job) => setJobs((list) => [job, ...list].slice(0, 6)), [])

  const run = useCallback(
    async <T,>(label: string, method: string, params: Record<string, unknown>): Promise<T | null> => {
      const id = `job-${++jobSeq}`
      push({ id, label, status: 'running', progress: 0, message: 'Starting…' })
      try {
        const result = await call<T>(method, params, id)
        const r = (result ?? {}) as Record<string, unknown>
        const output = typeof r.output === 'string' ? r.output : typeof r.output_dir === 'string' ? r.output_dir : undefined
        const warning = typeof r.warning === 'string' ? r.warning : ''
        patch(id, { status: 'done', progress: 1, message: warning || 'Done', output })
        return result
      } catch (err) {
        patch(id, { status: 'error', message: err instanceof Error ? err.message : String(err) })
        return null
      }
    },
    [patch, push]
  )

  const notify = useCallback(
    (label: string, message: string, status: 'done' | 'error' = 'done') => {
      push({ id: `job-${++jobSeq}`, label, status, progress: 1, message })
    },
    [push]
  )

  const dismissJob = useCallback((id: string) => setJobs((list) => list.filter((j) => j.id !== id)), [])

  const ask = useCallback(
    (request: Omit<PromptRequest, 'resolve'>) =>
      new Promise<Record<string, string> | null>((resolve) => setPrompt({ ...request, resolve })),
    []
  )

  const value = useMemo<Services>(
    () => ({ engine, jobs, run, notify, dismissJob, ask }),
    [engine, jobs, run, notify, dismissJob, ask]
  )

  return (
    <Ctx.Provider value={value}>
      {children}
      {prompt && (
        <PromptDialog
          request={prompt}
          onClose={(values) => {
            prompt.resolve(values)
            setPrompt(null)
          }}
        />
      )}
    </Ctx.Provider>
  )
}

function PromptDialog({
  request,
  onClose
}: {
  request: PromptRequest
  onClose(values: Record<string, string> | null): void
}): ReactNode {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(request.fields.map((f) => [f.name, f.initial ?? '']))
  )
  const first = useRef<HTMLInputElement>(null)
  useEffect(() => first.current?.focus(), [])
  const valid = request.fields.every((f) => f.optional || f.type === 'checkbox' || values[f.name].trim() !== '')

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose(null)}>
      <form
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={request.title}
        onKeyDown={(e) => e.key === 'Escape' && onClose(null)}
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) onClose(values)
        }}
      >
        <h2>{request.title}</h2>
        {request.body && <p className="muted">{request.body}</p>}
        {request.fields.map((f, i) =>
          f.type === 'checkbox' ? (
            <label key={f.name} className="check">
              <input
                type="checkbox"
                checked={values[f.name] === 'true'}
                onChange={(e) => setValues((v) => ({ ...v, [f.name]: String(e.target.checked) }))}
              />
              {f.label}
            </label>
          ) : (
          <label key={f.name} className="field">
            <span>{f.label}</span>
            <input
              ref={i === 0 ? first : undefined}
              type={f.type ?? 'text'}
              value={values[f.name]}
              placeholder={f.placeholder}
              autoComplete="off"
              onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
            />
            {f.hint && <small className="muted">{f.hint}</small>}
          </label>
          )
        )}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={() => onClose(null)}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={!valid}>
            {request.confirm ?? 'OK'}
          </button>
        </div>
      </form>
    </div>
  )
}
