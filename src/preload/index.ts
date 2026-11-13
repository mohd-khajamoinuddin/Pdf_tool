import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'
import type { EngineStatus, ProgressEvent, SuiteApi } from '../shared/api'

function subscribe<T>(channel: string, listener: (payload: T) => void): () => void {
  const handler = (_e: IpcRendererEvent, payload: T): void => listener(payload)
  ipcRenderer.on(channel, handler)
  return () => ipcRenderer.removeListener(channel, handler)
}

const api: SuiteApi = {
  engine: (method, params, jobId) => ipcRenderer.invoke('engine:call', method, params, jobId),
  engineStatus: () => ipcRenderer.invoke('engine:status'),
  onEngineStatus: (listener) => subscribe<EngineStatus>('engine:status', listener),
  onProgress: (listener) => subscribe<ProgressEvent>('engine:progress', listener),
  openFiles: (options) => ipcRenderer.invoke('dialog:open', options),
  openFolder: (options) => ipcRenderer.invoke('dialog:openFolder', options),
  saveFile: (options) => ipcRenderer.invoke('dialog:save', options),
  printToPdf: (output, options) => ipcRenderer.invoke('window:printToPdf', output, options),
  revealInFolder: (path) => ipcRenderer.invoke('shell:reveal', path),
  openPath: (path) => ipcRenderer.invoke('shell:open', path)
}

contextBridge.exposeInMainWorld('suite', api)
