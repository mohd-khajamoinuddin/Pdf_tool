// Built-in document templates. They are plain data shipped with the app.
import type { DocJson } from './editor'

type Mark = { type: string; attrs?: Record<string, unknown> }

const bold: Mark = { type: 'bold' }
const muted: Mark = { type: 'textStyle', attrs: { color: '#667085' } }

const t = (text: string, ...marks: Mark[]): DocJson => (marks.length ? { type: 'text', text, marks } : { type: 'text', text })
const p = (...content: DocJson[]): DocJson => (content.length ? { type: 'paragraph', content } : { type: 'paragraph' })
const aligned = (textAlign: string, ...content: DocJson[]): DocJson => ({ type: 'paragraph', attrs: { textAlign }, content })
const h = (level: number, text: string, textAlign?: string): DocJson => ({
  type: 'heading',
  attrs: textAlign ? { level, textAlign } : { level },
  content: [t(text)]
})
const list = (type: 'bulletList' | 'orderedList', ...items: string[]): DocJson => ({
  type,
  content: items.map((item) => ({ type: 'listItem', content: [p(t(item))] }))
})
const row = (kind: 'tableHeader' | 'tableCell', ...cells: string[]): DocJson => ({
  type: 'tableRow',
  content: cells.map((cell) => ({ type: kind, attrs: { colspan: 1, rowspan: 1 }, content: [cell ? p(t(cell)) : p()] }))
})
const table = (header: string[], ...rows: string[][]): DocJson => ({
  type: 'table',
  content: [row('tableHeader', ...header), ...rows.map((r) => row('tableCell', ...r))]
})
const doc = (...content: DocJson[]): DocJson => ({ type: 'doc', content })

export interface Template {
  id: string
  name: string
  blurb: string
  content: DocJson
}

export const TEMPLATES: Template[] = [
  { id: 'blank', name: 'Blank document', blurb: 'Start from an empty page', content: doc(p()) },
  {
    id: 'letter',
    name: 'Letter',
    blurb: 'Formal business letter',
    content: doc(
      p(t('Your Name', bold)),
      p(t('Street address'), { type: 'hardBreak' }, t('City, postcode')),
      p(t('Date', muted)),
      p(t('Recipient name'), { type: 'hardBreak' }, t('Company'), { type: 'hardBreak' }, t('Address')),
      p(t('Dear Recipient,')),
      p(t('Open with the reason you are writing. Keep the first paragraph to two or three sentences.')),
      p(t('Use the middle paragraphs for the detail the reader needs in order to act.')),
      p(t('Close by saying what you would like to happen next.')),
      p(t('Yours sincerely,')),
      p(),
      p(t('Your Name'))
    )
  },
  {
    id: 'report',
    name: 'Report',
    blurb: 'Title, summary, sections and a table',
    content: doc(
      h(1, 'Report title', 'center'),
      aligned('center', t('Author · Date', muted)),
      h(2, 'Summary'),
      p(t('State the conclusion first, in two or three sentences, so a reader who stops here still has the answer.')),
      h(2, 'Background'),
      p(t('What the reader needs to know to follow the findings.')),
      h(2, 'Findings'),
      list('orderedList', 'First finding', 'Second finding', 'Third finding'),
      table(['Measure', 'Before', 'After'], ['Example metric', '', ''], ['Example metric', '', '']),
      h(2, 'Recommendations'),
      list('bulletList', 'What to do', 'Who owns it', 'By when')
    )
  },
  {
    id: 'resume',
    name: 'Résumé',
    blurb: 'One-page CV layout',
    content: doc(
      h(1, 'Your Name', 'center'),
      aligned('center', t('Role · City · phone · email', muted)),
      { type: 'horizontalRule' },
      h(2, 'Profile'),
      p(t('Two or three lines on what you do and what you are looking for.')),
      h(2, 'Experience'),
      p(t('Job title, Company', bold), t('  —  2022 to present', muted)),
      list('bulletList', 'What you achieved, with a number where possible', 'Another result'),
      p(t('Job title, Company', bold), t('  —  2019 to 2022', muted)),
      list('bulletList', 'What you achieved', 'Another result'),
      h(2, 'Education'),
      p(t('Qualification, Institution', bold), t('  —  year', muted)),
      h(2, 'Skills'),
      p(t('Skill one · Skill two · Skill three'))
    )
  },
  {
    id: 'minutes',
    name: 'Meeting notes',
    blurb: 'Agenda, decisions and actions',
    content: doc(
      h(1, 'Meeting notes'),
      p(t('Date: ', bold), t(''), { type: 'hardBreak' }, t('Attendees: ', bold), t('')),
      h(2, 'Agenda'),
      list('orderedList', 'Topic', 'Topic'),
      h(2, 'Decisions'),
      list('bulletList', 'Decision and why'),
      h(2, 'Actions'),
      table(['Action', 'Owner', 'Due'], ['', '', ''], ['', '', ''])
    )
  },
  {
    id: 'invoice',
    name: 'Invoice',
    blurb: 'Works with mail merge fields',
    content: doc(
      h(1, 'Invoice'),
      p(t('Your company', bold), { type: 'hardBreak' }, t('Address · tax number', muted)),
      p(t('Bill to: ', bold), t('{{name}}'), { type: 'hardBreak' }, t('Invoice number: ', bold), t('{{invoice}}')),
      table(['Description', 'Quantity', 'Unit price', 'Amount'], ['', '', '', ''], ['', '', '', '']),
      aligned('right', t('Total due: ', bold), t('{{amount}}', bold)),
      p(t('Payment is due within 30 days.', muted))
    )
  }
]
