import { join } from 'node:path'
import { app, BrowserWindow, Menu, session } from 'electron'
import type { EngineStatus } from '../shared/api'
import { Engine } from './engine'
import { registerIpc } from './ipc'

const DEV_URL = !app.isPackaged ? process.env.ELECTRON_RENDERER_URL : undefined

// --- Offline guarantee, layer 1: switch off Chromium's own background traffic
// (component updates, safe-browsing lists, metrics, DNS prefetch, ...).
for (const flag of [
  'disable-background-networking',
  'disable-component-update',
  'disable-domain-reliability',
  'disable-sync',
  'disable-breakpad',
  'no-pings',
  'dns-prefetch-disable'
]) {
  app.commandLine.appendSwitch(flag)
}
app.commandLine.appendSwitch('disable-features', 'OptimizationHints,MediaRouter,Translate,AutofillServerCommunication')

let mainWindow: BrowserWindow | null = null

const engine = new Engine((status: EngineStatus) => {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('engine:status', status)
})

// --- Offline guarantee, layer 2: refuse every request that is not one of the
// app's own local files. In development the Vite dev server origin is allowed.
function lockDownNetwork(): void {
  const devOrigin = DEV_URL ? new URL(DEV_URL) : null
  const ses = session.defaultSession

  ses.webRequest.onBeforeRequest((details, callback) => {
    let allowed = false
    try {
      const url = new URL(details.url)
      allowed =
        ['file:', 'data:', 'blob:', 'devtools:', 'chrome-extension:'].includes(url.protocol) ||
        (devOrigin !== null && url.hostname === devOrigin.hostname && url.port === devOrigin.port)
    } catch {
      allowed = false
    }
    if (!allowed) console.warn('[offline] blocked request:', details.url)
    callback({ cancel: !allowed })
  })

  // No camera, microphone, geolocation, notifications, ... for web content. The
  // editors only need the local clipboard and full-screen (slide show).
  const allowed = new Set(['fullscreen', 'clipboard-read', 'clipboard-sanitized-write'])
  ses.setPermissionRequestHandler((_wc, permission, callback) => callback(allowed.has(permission)))
  ses.setPermissionCheckHandler((_wc, permission) => allowed.has(permission))
  // Never talk to a spell-check dictionary CDN.
  ses.setSpellCheckerEnabled(false)
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 980,
    minHeight: 620,
    show: false,
    backgroundColor: '#f5f6f8',
    title: 'DocSuite',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      devTools: !app.isPackaged
    }
  })

  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.on('closed', () => (mainWindow = null))

  // The UI is a single local page: no pop-ups, no navigating away from it.
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!DEV_URL || !url.startsWith(DEV_URL)) event.preventDefault()
  })

  if (DEV_URL) void mainWindow.loadURL(DEV_URL)
  else void mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  })

  void app.whenReady().then(() => {
    lockDownNetwork()
    if (app.isPackaged) Menu.setApplicationMenu(null)
    registerIpc(engine, () => mainWindow)
    createWindow()
    // Warm the engine up so the first action is instant; failures surface in the status bar.
    engine.start().catch((err) => console.error('[engine] failed to start:', err.message))

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow()
    })
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
  app.on('before-quit', () => engine.stop())
}
