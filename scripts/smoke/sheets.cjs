// Spreadsheets: open a CSV with formulas, check live calculation, type into the
// grid with real keys, format, add a chart, save as xlsx and csv, verify the files.
module.exports = async (t) => {
  const engine = (method, params) => t.js(`window.suite.engine(${JSON.stringify(method)}, ${JSON.stringify(params)})`)
  const canvasBox = () =>
    t.js(`(() => { const all = [...document.querySelectorAll('.sheets-grid canvas')].map(c => c.getBoundingClientRect())
      const r = all.sort((a, b) => b.width * b.height - a.width * a.height)[0]
      return r ? { x: r.left, y: r.top, w: r.width, h: r.height } : null })()`)

  await t.click('Spreadsheets')
  t.willOpen(t.file('data.csv'))
  await t.click('Open')
  t.check('open job completes', (await t.jobDone()) === 'done')
  t.check('grid canvas is rendered', await t.until(`document.querySelectorAll('.sheets-grid canvas').length > 0`))
  await t.sleep(1200) // first formula pass
  await t.clearJobs()
  const box = await canvasBox()
  t.check('grid has a usable size', !!box && box.w > 600 && box.h > 300, JSON.stringify(box))
  await t.shot('sheets-open')

  // ---- live formulas: the CSV holds =B2+C2; a CSV export writes the computed value
  const csv1 = t.outFile('calc.csv')
  t.willSave(csv1)
  await t.click('Save as…')
  t.check('csv export completes', (await t.jobDone()) === 'done')
  const lines = t.fs.existsSync(csv1) ? t.fs.readFileSync(csv1, 'utf8').replace(/^﻿/, '').trim().split(/\r?\n/) : []
  t.check('formulas were calculated by the grid', lines[1] === 'North,120,135,255' && lines[2] === 'South,98,110,208', lines.join(' | '))
  await t.clearJobs()

  // ---- chart from the data range (before the sheet gets extra cells)
  await t.click('Charts')
  await t.click('Bar')
  t.check('chart preview renders', await t.until(`!!document.querySelector('.chart-canvas canvas')`, 5000))
  await t.shot('sheets-chart')

  // ---- type a formula into an empty cell with real mouse + keyboard, then make it bold
  const x = Math.round(box.x + 320)
  const y = Math.round(box.y + 260)
  await t.mouse(x, y)
  await t.type('=6*7')
  await t.key('Enter')
  await t.sleep(400)
  await t.mouse(x, y)
  await t.key('b', ['control'])
  await t.sleep(400)
  t.check('editing marks the workbook as changed', await t.js(`!!document.querySelector('section:not([hidden]) .file-chip em')`))
  await t.shot('sheets-edited')

  // ---- save as xlsx and read the file back through the engine
  const xlsx = t.outFile('data.xlsx')
  t.willSave(xlsx)
  await t.click('Save as…')
  t.check('xlsx save completes', (await t.jobDone()) === 'done' && t.fs.existsSync(xlsx))
  const back = await engine('sheet.open', { input: xlsx })
  let typed = null
  let style = null
  if (back.ok) {
    const wb = back.result.workbook
    const cells = wb.sheets[wb.sheetOrder[0]].cellData
    for (const row of Object.values(cells)) for (const cell of Object.values(row)) if (cell.f === '=6*7') typed = cell
    style = typed && typed.s ? wb.styles[typed.s] : null
    t.check('original cells survived', cells['1']['0'].v === 'North' && cells['1']['3'].f === '=B2+C2')
  }
  t.check('typed formula was saved', !!typed, back.ok ? '' : JSON.stringify(back.error))
  t.check('bold formatting was saved', !!style && style.bl === 1, JSON.stringify(style))
  t.check('chart was written into the xlsx', back.ok && back.result.notes.some((n) => n.includes('1 chart(s)')), back.ok ? back.result.notes.join('; ') : '')
  t.check(
    'saved workbook becomes the open document',
    await t.js(`document.querySelector('section:not([hidden]) .file-chip')?.textContent === 'data.xlsx'`)
  )

  // ---- the computed result of the typed formula is in a values-only export
  await t.clearJobs()
  const csv2 = t.outFile('calc2.csv')
  t.willSave(csv2)
  await t.click('Save as…')
  await t.jobDone()
  const text = t.fs.existsSync(csv2) ? t.fs.readFileSync(csv2, 'utf8') : ''
  t.check('typed formula evaluates to 42', /(^|,)42(,|\r?\n|$)/m.test(text), text.replace(/\r?\n/g, ' | ').slice(0, 200))
}
