import type { PrintOptions } from '../../../shared/api'

/**
 * Export arbitrary HTML as a PDF through Chromium's print pipeline.
 *
 * The HTML is mounted in a hidden container; while printing, everything else
 * in the window is hidden, so only that container reaches the page. `css`
 * should style it (and may set `@page` size and margins).
 */
export async function printHtmlToPdf(
  output: string,
  html: string,
  css: string,
  options?: PrintOptions
): Promise<{ ok: true } | { ok: false; message: string }> {
  const root = document.createElement('div')
  root.id = 'print-root'
  root.innerHTML = html
  const style = document.createElement('style')
  style.textContent = `
    @media screen { #print-root { display: none; } }
    @media print {
      body > *:not(#print-root) { display: none !important; }
      html, body { height: auto !important; overflow: visible !important; background: #fff !important; }
    }
    ${css}`
  document.body.append(style, root)
  try {
    // Embedded images must be decoded before the print snapshot is taken.
    await Promise.all(Array.from(root.querySelectorAll('img')).map((img) => img.decode().catch(() => undefined)))
    return await window.suite.printToPdf(output, options)
  } finally {
    root.remove()
    style.remove()
  }
}
