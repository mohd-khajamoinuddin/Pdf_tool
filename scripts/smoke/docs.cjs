// Documents: template -> type with real keys -> format -> table + image -> save .docx
// -> verify the file -> export PDF -> mail merge -> reopen.
module.exports = async (t) => {
  const engine = (method, params) => t.js(`window.suite.engine(${JSON.stringify(method)}, ${JSON.stringify(params)})`)
  const press = (label) =>
    t.js(`(() => { const b = document.querySelector('section:not([hidden]) [aria-label=${JSON.stringify(label)}]'); if (!b || b.disabled) return false; b.click(); return true })()`)
  const textOf = (node) => (node.type === 'text' ? node.text : (node.content || []).map(textOf).join(''))

  await t.click('Documents')
  t.check('template gallery is shown', await t.until(`document.querySelectorAll('.doc-template').length >= 5`))
  await t.shot('docs-gallery')
  await t.js(`[...document.querySelectorAll('.doc-template')].find(b => b.querySelector('strong').textContent === 'Blank document').click()`)
  t.check('editor opens', await t.until(`!!document.querySelector('.doc-content .ProseMirror')`))

  // ---- type and format with real input
  await t.js(`document.querySelector('.doc-content .ProseMirror').focus()`)
  await t.type('Hello world')
  await t.key('a', ['control'])
  await press('Bold (Ctrl+B)')
  t.check('typed text is bold in the editor', await t.until(`document.querySelector('.doc-content strong')?.textContent === 'Hello world'`, 3000))
  t.check('toolbar reflects the selection', await t.js(`document.querySelector('[aria-label="Bold (Ctrl+B)"]').getAttribute('aria-pressed') === 'true'`))
  await t.js(`(() => { const s = document.querySelector('[aria-label="Paragraph style"]'); s.value = '1'; s.dispatchEvent(new Event('change', { bubbles: true })) })()`)
  t.check('paragraph style changes to Heading 1', await t.until(`document.querySelector('.doc-content h1')?.textContent === 'Hello world'`, 3000))

  await t.key('End')
  await t.key('Enter')
  await t.type('Second paragraph')
  await t.key('Enter')
  await t.click('Table')
  await t.click('Insert 2 × 2')
  t.check('table inserted', await t.until(`document.querySelectorAll('.doc-content td').length === 4`, 3000))
  await t.type('cell A')

  const png = t.file('picture.png')
  t.willOpen(png)
  await press('Insert image')
  t.check('image inserted', await t.until(`!!document.querySelector('.doc-content img')`, 5000))
  await t.shot('docs-editing')
  t.check('document is marked as edited', await t.js(`!!document.querySelector('section:not([hidden]) .file-chip em')`))

  // ---- save and verify the written file
  const docx = t.outFile('note.docx')
  t.fs.rmSync(docx, { force: true })
  t.willSave(docx)
  await t.clearJobs()
  await t.click('Save as…')
  const saved = await t.jobDone()
  t.check('docx save completes', saved === 'done' && t.fs.existsSync(docx), await t.js(`document.querySelector('.job')?.textContent ?? ''`))
  const back = await engine('doc.open', { input: docx })
  if (t.check('saved docx can be read back', back.ok, back.ok ? '' : JSON.stringify(back.error))) {
    const blocks = back.result.content.content
    const head = blocks[0]
    t.check('heading + bold survived', head.type === 'heading' && head.attrs.level === 1 && textOf(head) === 'Hello world' && (head.content[0].marks || []).some((m) => m.type === 'bold'))
    t.check('second paragraph survived', blocks.some((b) => b.type === 'paragraph' && textOf(b) === 'Second paragraph'))
    const table = blocks.find((b) => b.type === 'table')
    t.check('table survived', !!table && table.content.length === 2 && textOf(table).includes('cell A'))
    t.check('image survived', JSON.stringify(blocks).includes('"type":"image"'))
  }
  await t.clearJobs()

  // ---- PDF export through the print pipeline
  const pdf = t.outFile('note.pdf')
  t.willSave(pdf)
  await t.click('Export PDF')
  t.check('PDF export writes a file', await t.until(`document.querySelector('.job.done') !== null`, 20000) && t.fs.existsSync(pdf))
  const info = await engine('pdf.info', { input: pdf })
  t.check('exported PDF is A4 with 1 page', info.ok && info.result.pages === 1 && Math.abs(info.result.page_sizes[0][0] - 595) < 2, info.ok ? JSON.stringify(info.result.page_sizes) : JSON.stringify(info.error))
  const txt = t.outFile('note-pdf.txt')
  t.willSave(txt)
  await t.js(`window.suite.saveFile({})`) // grants the output path
  const converted = await engine('convert.run', { input: pdf, output: txt })
  const pdfText = converted.ok ? t.fs.readFileSync(txt, 'utf8') : ''
  t.check('PDF contains the document text and nothing of the app chrome', pdfText.includes('Hello world') && pdfText.includes('cell A') && !pdfText.includes('DocSuite') && !pdfText.includes('Save as'), pdfText.slice(0, 120).replace(/\s+/g, ' '))
  await t.clearJobs()

  // ---- mail merge
  const data = t.file('people.csv')
  t.fs.writeFileSync(data, 'name,city\nAda,London\nGrace,New York\n')
  t.willOpen(data)
  await t.click('Mail merge')
  t.check('merge panel lists the fields', await t.until(`document.querySelectorAll('.doc-field').length === 2`, 5000))
  await t.js(`document.querySelector('.doc-field').click()`)
  t.check('placeholder inserted at the cursor', await t.until(`document.querySelector('.doc-content').textContent.includes('{{name}}')`, 3000))
  await t.shot('docs-merge')
  await t.click('Generate…')
  t.check('mail merge completes', (await t.jobDone()) === 'done')
  const merged = t.outFile('note-2.docx')
  t.check('one document per record', t.fs.existsSync(t.outFile('note-1.docx')) && t.fs.existsSync(merged))
  const second = await engine('doc.open', { input: merged })
  t.check('placeholders were filled', second.ok && textOf(second.result.content).includes('Grace') && !textOf(second.result.content).includes('{{'))
  await t.clearJobs()

  // ---- reopen the saved file in the editor
  t.willOpen(docx)
  await t.click('Open')
  await t.jobDone()
  t.check(
    'reopened document renders heading, table and image',
    await t.until(`document.querySelector('.doc-content h1')?.textContent === 'Hello world' && document.querySelectorAll('.doc-content td').length === 4 && !!document.querySelector('.doc-content img') && !document.querySelector('.doc-content').textContent.includes('{{name}}')`, 5000)
  )
}
