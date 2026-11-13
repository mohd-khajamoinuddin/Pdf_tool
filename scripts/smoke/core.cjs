// Shell, offline guarantee and path allow-list.
module.exports = async (t) => {
  await t.shot('core-home')
  const blocked = await t.session.defaultSession.fetch('https://example.com/').then(() => false, () => true)
  t.check('main-process request to the internet is blocked', blocked)
  t.check('renderer request to the internet is blocked', await t.js(`fetch('https://example.com/').then(() => false, () => true)`))
  t.check('renderer has no Node access', await t.js(`typeof require === 'undefined' && typeof process === 'undefined'`))
  const denied = await t.js(`window.suite.engine('pdf.info', { input: ${JSON.stringify(t.file('sample.pdf'))} })`)
  t.check('un-picked path is refused', denied.ok === false && denied.error.code === 'path_not_granted')
}
