import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'

// Production builds get a strict Content-Security-Policy: no remote origins at
// all. It is injected at build time only, because the dev server needs inline
// scripts and a websocket for hot reload.
const CSP =
  "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; connect-src 'none'; " +
  "object-src 'none'; base-uri 'none'; form-action 'none'"

function strictCsp(): Plugin {
  return {
    name: 'docsuite-strict-csp',
    apply: 'build',
    transformIndexHtml: (html) =>
      html.replace('<!-- csp -->', `<meta http-equiv="Content-Security-Policy" content="${CSP}" />`)
  }
}

export default defineConfig({
  main: {},
  preload: {},
  renderer: {
    plugins: [react(), strictCsp()]
  }
})
