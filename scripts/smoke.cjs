// End-to-end smoke test of the built app.
//
//   npm run smoke                       (build + samples + all steps)
//   npx electron -r ./scripts/smoke.cjs . <work-dir> [--only=core,sheets]
//
// <work-dir> must contain sample.pdf and data.csv (scripts/make_samples.py).
// Steps live in scripts/smoke/<name>.cjs and export `async (t) => {}`.
// Only the native file dialogs are stubbed; the window, preload bridge, IPC,
// path grants and Python engine are the real thing.
const { app, dialog, session } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const args = process.argv.slice(1).filter((a) => !a.startsWith('-'))
const work = path.resolve(args[args.length - 1])
const onlyArg = process.argv.find((a) => a.startsWith('--only='))
const only = (onlyArg ? onlyArg.slice(7) : process.env.SMOKE_ONLY || 'core,pdf,sheets,docs,slides').split(',')
const shots = path.join(work, 'shots')
const out = path.join(work, 'out')
fs.mkdirSync(shots, { recursive: true })
fs.mkdirSync(out, { recursive: true })

// A private profile per work dir, so several smoke runs (or a running dev app)
// do not trip the single-instance lock.
app.setPath('userData', path.join(work, 'profile'))

let nextOpen = []
let nextSave = null
let nextFolder = out
dialog.showOpenDialog = async (_w, opts) =>
  opts.properties.includes('openDirectory')
    ? { canceled: false, filePaths: [nextFolder] }
    : { canceled: nextOpen.length === 0, filePaths: nextOpen }
dialog.showSaveDialog = async () => ({ canceled: !nextSave, filePath: nextSave })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok: !!ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + detail : ''}`)
  return !!ok
}

app.on('browser-window-created', (_e, win) => {
  const wc = win.webContents
  const js = (code) => wc.executeJavaScript(code, true)
  const consoleErrors = []
  wc.on('console-message', (e) => {
    // The offline probe in core.cjs is *supposed* to be refused; that is not a defect.
    if ((e.level === 'error' || e.level === 3) && !e.message.includes('example.com')) consoleErrors.push(e.message)
  })

  /** Everything a step needs. */
  const t = {
    work, out, fs, path, session, wc, win, js, sleep, check, consoleErrors,
    file: (...parts) => path.join(work, ...parts),
    outFile: (...parts) => path.join(out, ...parts),
    /** Answer the next native dialogs. */
    willOpen: (...files) => (nextOpen = files),
    willSave: (file) => (nextSave = file),
    willPickFolder: (dir) => (nextFolder = dir),
    /** Click the first enabled button with exactly this label in the visible workspace, the nav or a dialog. */
    click: async (text) => {
      // Workspaces load on first use, so the button may take a moment to exist.
      for (const end = Date.now() + 8000; Date.now() < end; await sleep(100)) {
        const done = await js(`(() => { const b = [...document.querySelectorAll('section:not([hidden]) button, nav button, .dialog button')]
          .find(b => b.textContent.trim() === ${JSON.stringify(text)} && !b.disabled); if (!b) return false; b.click(); return true })()`)
        if (done) return true
      }
      console.log(`      (no enabled button labelled "${text}")`)
      return false
    },
    /** Poll a JS expression in the page until it is truthy. */
    until: async (code, ms = 15000) => {
      for (const end = Date.now() + ms; Date.now() < end; await sleep(150)) if (await js(code)) return true
      return false
    },
    /** Wait for the newest job in the tray to finish; resolves 'done' | 'error' | 'timeout'. */
    jobDone: async (ms = 30000) => {
      for (const end = Date.now() + ms; Date.now() < end; await sleep(150)) {
        const s = await js(`(() => { const j = document.querySelector('.job'); return j ? j.className : '' })()`)
        if (s.includes('done')) return 'done'
        if (s.includes('error')) return 'error'
      }
      return 'timeout'
    },
    clearJobs: () => js(`document.querySelectorAll('.job .icon-btn').forEach(b => b.click())`),
    /** Set a React-controlled <input>/<textarea> value. */
    fill: (selector, value) =>
      js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false
        const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)})
        el.dispatchEvent(new Event('input', { bubbles: true })); return true })()`),
    /** Real keyboard input into whatever has focus. */
    type: async (text) => {
      for (const ch of text) {
        wc.sendInputEvent({ type: 'char', keyCode: ch })
        await sleep(5)
      }
    },
    key: async (keyCode, modifiers = []) => {
      wc.sendInputEvent({ type: 'keyDown', keyCode, modifiers })
      wc.sendInputEvent({ type: 'keyUp', keyCode, modifiers })
      await sleep(30)
    },
    /** Real mouse click at page coordinates. */
    mouse: async (x, y, clickCount = 1) => {
      wc.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount })
      wc.sendInputEvent({ type: 'mouseUp', x, y, button: 'left', clickCount })
      await sleep(50)
    },
    /** Screenshots are for people to look at; a failed capture (e.g. window occluded) must not fail the run. */
    shot: async (name) => {
      try {
        fs.writeFileSync(path.join(shots, name + '.png'), (await wc.capturePage()).toPNG())
      } catch (err) {
        console.log(`      (screenshot ${name} skipped: ${err.message})`)
      }
    }
  }

  wc.once('did-finish-load', async () => {
    try {
      check('engine becomes ready', await t.until(`document.querySelector('.dot.ready') !== null`, 30000))
      for (const name of only) {
        console.log(`\n== ${name}`)
        await t.clearJobs()
        await require(path.join(__dirname, 'smoke', name + '.cjs'))(t)
      }
      check('no console errors', consoleErrors.length === 0, consoleErrors.join(' | ').slice(0, 400))
    } catch (err) {
      check('smoke run', false, String((err && err.stack) || err))
    }
    const failed = results.filter((r) => !r.ok).length
    console.log(`\n${results.length - failed}/${results.length} checks passed`)
    app.exit(failed ? 1 : 0)
  })
})
