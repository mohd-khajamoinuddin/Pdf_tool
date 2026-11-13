// PDF Studio: open, convert, protect, then edit (draw, type, sign, organise pages) and save.
module.exports = async (t) => {
  const drag = async (x1, y1, x2, y2) => {
    t.wc.sendInputEvent({ type: 'mouseDown', x: x1, y: y1, button: 'left', clickCount: 1 })
    for (let i = 1; i <= 6; i++) {
      t.wc.sendInputEvent({
        type: 'mouseMove',
        x: Math.round(x1 + ((x2 - x1) * i) / 6),
        y: Math.round(y1 + ((y2 - y1) * i) / 6),
        button: 'left',
        modifiers: ['leftButtonDown']
      })
      await t.sleep(20)
    }
    t.wc.sendInputEvent({ type: 'mouseUp', x: x2, y: y2, button: 'left', clickCount: 1 })
    await t.sleep(80)
  }
  const rectOf = (selector) =>
    t.js(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height } })()`)
  const pressLabel = (label) =>
    t.js(`(() => { const b = document.querySelector('section:not([hidden]) [aria-label=${JSON.stringify(label)}]'); if (!b || b.disabled) return false; b.click(); return true })()`)

  await t.click('PDF Studio')
  t.willOpen(t.file('sample.pdf'))
  await t.click('Open')
  t.check(
    'PDF opens with page canvas + 3 thumbnails',
    await t.until(`!!document.querySelector('.pdf-sheet img') && document.querySelectorAll('.pdf-thumb img').length === 3`)
  )

  // ---- conversions on the unmodified file
  const docx = t.outFile('sample.docx')
  t.willSave(docx)
  await t.click('Convert')
  await t.click('To Word (.docx)')
  t.check('PDF -> Word job completes', (await t.jobDone()) === 'done')
  t.check('docx written to disk', t.fs.existsSync(docx) && t.fs.statSync(docx).size > 5000)

  await t.clearJobs()
  const xlsx = t.outFile('sample.xlsx')
  t.willSave(xlsx)
  await t.click('Convert')
  await t.click('To Excel (.xlsx)')
  t.check('PDF -> Excel job completes', (await t.jobDone()) === 'done' && t.fs.existsSync(xlsx))

  await t.clearJobs()
  const locked = t.outFile('sample-protected.pdf')
  t.willSave(locked)
  await t.click('Protect')
  await t.until(`document.querySelector('.dialog') !== null`)
  await t.js(`(() => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    ;[...document.querySelectorAll('.dialog input[type=password]')].slice(0, 2).forEach(i => { set.call(i, 'hunter2'); i.dispatchEvent(new Event('input', { bubbles: true })) }) })()`)
  await t.shot('pdf-protect-dialog')
  await t.js(`document.querySelector('.dialog .btn.primary').click()`)
  t.check('Protect job completes', (await t.jobDone()) === 'done')
  const reopened = await t.js(`window.suite.engine('pdf.info', { input: ${JSON.stringify(locked)} })`)
  t.check('protected copy demands a password', reopened.ok === false && reopened.error.code === 'password_required')
  await t.clearJobs()

  // ---- certificate-based signing (works on the saved file, so it runs before any edits)
  const signedPdf = t.outFile('sample-signed.pdf')
  t.willOpen(t.file('sample-signer.p12'))
  t.willSave(signedPdf)
  await t.click('Sign')
  await t.until(`document.querySelector('.dialog') !== null`)
  await t.fill('.dialog input[type=password]', 'test')
  await t.js(`document.querySelector('.dialog .btn.primary').click()`)
  t.check('Sign job completes', (await t.jobDone()) === 'done', await t.js(`document.querySelector('.job')?.textContent ?? ''`))
  t.check(
    'signed PDF opens and shows a valid signature',
    await t.until(`document.querySelector('.pdf-sigs li.ok strong')?.textContent === 'Sample Signer'`, 8000)
  )
  const sigs = await t.js(`window.suite.engine('pdf.signatures', { input: ${JSON.stringify(signedPdf)} })`)
  t.check('signature verifies and covers the whole file', sigs.ok && sigs.result.signatures.length === 1 && sigs.result.signatures[0].ok && sigs.result.signatures[0].covers_whole_file)
  await t.shot('pdf-signed')
  const stray = await t.js(`window.suite.engine('pdf.sign', { input: ${JSON.stringify(signedPdf)}, output: ${JSON.stringify(signedPdf + '.x.pdf')}, certificate: 'C:/Windows/win.ini' })`)
  t.check('a certificate path the user did not pick is refused', stray.ok === false && stray.error.code === 'path_not_granted')
  await t.clearJobs()
  // Carry on with the unsigned sample for the editing checks.
  t.willOpen(t.file('sample.pdf'))
  await t.click('Open')
  await t.until(`document.querySelector('section:not([hidden]) .file-chip')?.textContent === 'sample.pdf' && document.querySelectorAll('.pdf-thumb img').length === 3`)

  // ---- edit text that is already in the PDF
  await pressLabel('Edit text')
  t.check('existing text lines become clickable', await t.until(`document.querySelectorAll('.pdf-line').length > 5`, 8000))
  const found = await t.js(`window.suite.engine('pdf.text_lines', { input: ${JSON.stringify(t.file('sample.pdf'))}, page: 0 })`)
  const titleIndex = found.ok ? found.result.lines.findIndex((l) => l.text === 'Quarterly Report') : -1
  const titleBox = await rectOf(`.pdf-line[data-line="${titleIndex}"]`)
  await t.mouse(Math.round(titleBox.x + titleBox.w / 2), Math.round(titleBox.y + titleBox.h / 2))
  t.check('clicking a line opens it with its current text', await t.until(`document.querySelector('.pdf-typing')?.value === 'Quarterly Report'`, 3000))
  await t.key('a', ['control'])
  await t.type('Annual Summary')
  await t.key('Enter', ['control'])
  t.check(
    'the changed line is shown in place of the original',
    await t.until(`[...document.querySelectorAll('.pdf-overlay text')].some(n => n.textContent.trim() === 'Annual Summary') && !document.querySelector('.pdf-line[data-line="${titleIndex}"]')`, 3000)
  )
  await t.shot('pdf-edit-text')

  // ---- annotate with real pointer and keyboard input
  const sheet = await rectOf('.pdf-overlay')
  await pressLabel('Rectangle')
  await drag(sheet.x + 60, sheet.y + 260, sheet.x + 220, sheet.y + 340)
  t.check('dragging with the Rectangle tool draws a box', await t.until(`document.querySelectorAll('.pdf-overlay rect[data-id]').length === 1`, 3000))

  await pressLabel('Text')
  await t.mouse(Math.round(sheet.x + 80), Math.round(sheet.y + 380))
  t.check('Text tool opens an editor on the page', await t.until(`!!document.querySelector('.pdf-typing')`, 3000))
  await t.type('Approved 2026')
  await t.key('Enter', ['control'])
  t.check(
    'typed text becomes an annotation',
    await t.until(`[...document.querySelectorAll('.pdf-overlay text')].some(n => n.textContent.trim() === 'Approved 2026')`, 3000)
  )

  await t.click('Signature')
  await t.until(`!!document.querySelector('.sig-canvas')`)
  const pad = await rectOf('.sig-canvas')
  await drag(pad.x + 60, pad.y + 120, pad.x + 300, pad.y + 60)
  await t.click('Place signature')
  t.check('drawn signature is placed as an image', await t.until(`document.querySelectorAll('.pdf-overlay image').length === 1`, 3000))
  await t.shot('pdf-annotated')

  // Undo removes the signature, redo brings it back.
  await pressLabel('Undo')
  const afterUndo = await t.js(`document.querySelectorAll('.pdf-overlay image').length`)
  await pressLabel('Redo')
  t.check('undo / redo', afterUndo === 0 && (await t.js(`document.querySelectorAll('.pdf-overlay image').length`)) === 1)

  // ---- organise pages: rotate page 2, delete page 3
  await pressLabel('Rotate page 2')
  await pressLabel('Delete page 3')
  t.check('page deleted in the organiser', await t.until(`document.querySelectorAll('.pdf-thumb').length === 2`, 3000))

  // ---- save and verify the file that was written
  const edited = t.outFile('sample-edited.pdf')
  t.willSave(edited)
  await t.click('Save as…')
  t.check('Save job completes', (await t.jobDone()) === 'done')
  t.check(
    'app continues on the saved file',
    await t.until(`document.querySelector('section:not([hidden]) .file-chip')?.textContent.startsWith('sample-edited.pdf') && document.querySelectorAll('.pdf-thumb').length === 2`)
  )
  const info = await t.js(`window.suite.engine('pdf.info', { input: ${JSON.stringify(edited)} })`)
  t.check('saved PDF has 2 pages', info.ok && info.result.pages === 2)
  // Page 2 was rotated a quarter turn, so the viewer now reports it as landscape.
  t.check('rotation was saved', info.ok && info.result.page_sizes[1][0] > info.result.page_sizes[1][1], JSON.stringify(info.result && info.result.page_sizes))

  await t.clearJobs()
  const txt = t.outFile('sample-edited.txt')
  t.willSave(txt)
  await t.click('Convert')
  await t.click('To plain text')
  await t.jobDone()
  const text = t.fs.existsSync(txt) ? t.fs.readFileSync(txt, 'utf8') : ''
  t.check('typed annotation is real text in the saved PDF', text.includes('Approved 2026') && text.includes('Revenue grew steadily'))
  t.check('edited line was replaced in the saved PDF (old text is gone)', text.includes('Annual Summary') && !text.includes('Quarterly Report'), text.slice(0, 80).replace(/\s+/g, ' '))
  t.check('deleted page is gone', !text.includes('Appendix'))
  await t.shot('pdf-saved')
}
