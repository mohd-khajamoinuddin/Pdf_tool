// Slides: theme -> edit text with real keys -> add shape + image -> drag with the mouse
// -> add slide + transition -> save .pptx -> verify -> export PDF + PNGs -> reopen -> present.
module.exports = async (t) => {
  const engine = (method, params) => t.js(`window.suite.engine(${JSON.stringify(method)}, ${JSON.stringify(params)})`)
  const press = (label) =>
    t.js(`(() => { const b = document.querySelector('section:not([hidden]) [aria-label=${JSON.stringify(label)}]'); if (!b || b.disabled) return false; b.click(); return true })()`)
  const canvas = () =>
    t.js(`(() => { const r = document.querySelector('.sl-canvas').getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height } })()`)
  const drag = async (x1, y1, x2, y2) => {
    t.wc.sendInputEvent({ type: 'mouseDown', x: x1, y: y1, button: 'left', clickCount: 1 })
    for (let i = 1; i <= 8; i++) {
      t.wc.sendInputEvent({ type: 'mouseMove', x: Math.round(x1 + ((x2 - x1) * i) / 8), y: Math.round(y1 + ((y2 - y1) * i) / 8), button: 'left', modifiers: ['leftButtonDown'] })
      await t.sleep(25)
    }
    t.wc.sendInputEvent({ type: 'mouseUp', x: x2, y: y2, button: 'left', clickCount: 1 })
    await t.sleep(150)
  }
  const inspectorValue = (label) =>
    t.js(`(() => { const l = [...document.querySelectorAll('.sl-num')].find(n => n.querySelector('span').textContent === ${JSON.stringify(label)}); return l ? Number(l.querySelector('input').value) : null })()`)

  await t.click('Slides')
  t.check('theme gallery is shown', await t.until(`document.querySelectorAll('.sl-theme').length === 6`))
  await t.js(`[...document.querySelectorAll('.sl-theme')].find(b => b.querySelector('strong').textContent === 'Midnight').click()`)
  t.check('deck opens with a rendered slide and thumbnail', await t.until(`!!document.querySelector('.sl-canvas canvas') && document.querySelectorAll('.sl-thumb canvas').length === 1`))
  const box = await canvas()
  const k = box.w / 960 // screen pixels per slide point
  t.check('stage is fitted to the window', box.w > 400 && box.h > 200 && Math.abs(box.w / box.h - 16 / 9) < 0.02, JSON.stringify(box))

  // ---- edit the title in place with real input (title box: x 80, y 162, w 800, h 110)
  const tx = Math.round(box.x + 300 * k)
  const ty = Math.round(box.y + 190 * k)
  await t.mouse(tx, ty, 1)
  await t.mouse(tx, ty, 2)
  t.check('double-click opens the text editor', await t.until(`!!document.querySelector('.sl-typing')`, 3000))
  await t.key('a', ['control'])
  await t.type('Q3 results')
  await t.key('Enter', ['control'])
  await t.sleep(200)

  // ---- add a shape and an image
  await t.click('Shape')
  await t.click('Ellipse')
  t.check('new shape is selected (inspector shows it)', await t.until(`document.querySelector('.sl-inspector h3')?.textContent === 'Shape'`, 3000))
  const beforeX = await inspectorValue('X')
  await t.sleep(400) // the canvas repaints on the next frame; hit-testing needs the new shape drawn

  // drag the ellipse (centred on the slide) 120 px to the right, 60 px down
  const cx = Math.round(box.x + box.w / 2)
  const cy = Math.round(box.y + box.h / 2)
  await drag(cx, cy, cx + 120, cy + 60)
  const afterX = await inspectorValue('X')
  t.check('dragging with the mouse moves the element', beforeX !== null && afterX !== null && Math.abs(afterX - beforeX - 120 / k) < 4, `${beforeX} -> ${afterX}`)

  const png = t.file('picture.png')
  t.willOpen(png)
  await t.click('Image')
  t.check('image placed', await t.until(`document.querySelector('.sl-inspector h3')?.textContent === 'Image'`, 5000))
  await t.shot('slides-editing')

  // undo removes the image, redo restores it
  await t.click('Undo')
  await t.click('Redo')

  // ---- second slide with a transition
  await t.click('Slide')
  t.check('slide added', await t.until(`document.querySelectorAll('.sl-thumb').length === 2`, 3000))
  await t.js(`(() => { const s = document.querySelector('[aria-label="Transition"]'); s.value = 'push'; s.dispatchEvent(new Event('change', { bubbles: true })) })()`)
  await t.fill('.sl-notes textarea', 'Mention the forecast')
  await t.sleep(300)

  // ---- save and verify the written file
  const pptx = t.outFile('deck.pptx')
  t.fs.rmSync(pptx, { force: true })
  t.willSave(pptx)
  await t.clearJobs()
  await t.click('Save as…')
  t.check('pptx save completes', (await t.jobDone()) === 'done' && t.fs.existsSync(pptx), await t.js(`document.querySelector('.job')?.textContent ?? ''`))
  const back = await engine('slides.open', { input: pptx })
  if (t.check('saved pptx can be read back', back.ok, back.ok ? '' : JSON.stringify(back.error))) {
    const [first, second] = back.result.deck.slides
    const title = first.elements.find((e) => e.type === 'text' && e.text === 'Q3 results')
    t.check('typed title was saved with its formatting', !!title && title.bold === true && title.fontSize === 44 && title.color === '#ffffff')
    t.check('background, shape and image were saved', first.background === '#0b1f33' && first.elements.some((e) => e.type === 'shape' && e.shape === 'ellipse') && first.elements.some((e) => e.type === 'image'))
    const ellipse = first.elements.find((e) => e.shape === 'ellipse')
    t.check('saved position matches the drag', !!ellipse && Math.abs(ellipse.x - afterX) < 1, `${ellipse && ellipse.x} vs ${afterX}`)
    t.check('second slide: bullets, transition and notes', second.transition.type === 'push' && second.notes === 'Mention the forecast' && second.elements.some((e) => e.type === 'text' && e.bullets), JSON.stringify({ tr: second.transition, notes: second.notes, bullets: second.elements.map((e) => e.bullets) }))
  }
  await t.clearJobs()

  // ---- exports
  const pdf = t.outFile('deck.pdf')
  t.willSave(pdf)
  await t.click('Export')
  await t.click('PDF (one slide per page)')
  t.check('PDF export completes', (await t.jobDone()) === 'done')
  const info = await engine('pdf.info', { input: pdf })
  t.check('PDF has one 16:9 page per slide', info.ok && info.result.pages === 2 && info.result.page_sizes[0][0] === 960 && info.result.page_sizes[0][1] === 540)
  await t.clearJobs()
  await t.click('Export')
  await t.click('Images (PNG per slide)')
  t.check('image export completes', (await t.jobDone()) === 'done')
  const shot1 = t.outFile('deck-01.png')
  t.check('PNG per slide at export resolution', t.fs.existsSync(shot1) && t.fs.existsSync(t.outFile('deck-02.png')) && t.fs.statSync(shot1).size > 20000, t.fs.existsSync(shot1) ? t.fs.statSync(shot1).size + ' bytes' : 'missing')
  await t.clearJobs()

  // ---- reopen the saved deck
  t.willOpen(pptx)
  await t.click('Open')
  await t.jobDone()
  t.check('reopened deck shows both slides', await t.until(`document.querySelectorAll('.sl-thumb canvas').length === 2 && document.querySelector('section:not([hidden]) .file-chip')?.textContent === 'deck.pptx'`, 5000))
  await t.clearJobs()
  await t.shot('slides-reopened')

  // ---- slide show
  await t.click('Present')
  t.check('slide show starts', await t.until(`!!document.querySelector('.sl-show canvas')`, 3000))
  await t.key('Right')
  t.check('arrow key advances', await t.until(`document.querySelector('.sl-show-count')?.textContent.trim() === '2 / 2'`, 3000))
  await t.shot('slides-show')
  await t.key('Escape')
  t.check('Esc ends the show', await t.until(`!document.querySelector('.sl-show')`, 3000))
}
