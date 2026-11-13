// TipTap configuration for the word processor, plus the few document
// operations that are not single built-in commands.
import { Highlight } from '@tiptap/extension-highlight'
import { Image } from '@tiptap/extension-image'
import { TableKit } from '@tiptap/extension-table'
import { TextAlign } from '@tiptap/extension-text-align'
import { TextStyleKit } from '@tiptap/extension-text-style'
import { mergeAttributes, Node, type Editor, type JSONContent } from '@tiptap/react'
import { StarterKit } from '@tiptap/starter-kit'

export type DocJson = JSONContent

/** A hard page break: a block that forces the following content onto a new page. */
const PageBreak = Node.create({
  name: 'pageBreak',
  group: 'block',
  atom: true,
  selectable: true,
  parseHTML: () => [{ tag: 'div[data-page-break]' }],
  renderHTML: ({ HTMLAttributes }) => ['div', mergeAttributes(HTMLAttributes, { 'data-page-break': '', class: 'page-break' })]
})

export const extensions = [
  // Links are off: an offline editor must never fetch or open a URL.
  StarterKit.configure({ link: false }),
  TextAlign.configure({ types: ['heading', 'paragraph'] }),
  TextStyleKit,
  Highlight.configure({ multicolor: true }),
  TableKit.configure({ table: { resizable: true } }),
  Image.configure({
    inline: true,
    allowBase64: true,
    resize: { enabled: true, directions: ['bottom-right'], minWidth: 24, minHeight: 24, alwaysPreserveAspectRatio: true }
  }),
  PageBreak
]

export const FONTS = ['Arial', 'Calibri', 'Cambria', 'Courier New', 'Georgia', 'Segoe UI', 'Tahoma', 'Times New Roman', 'Verdana']
export const SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72]

export function insertPageBreak(editor: Editor): void {
  editor.chain().focus().insertContent({ type: 'pageBreak' }).run()
}

/** Replace every occurrence of `find` in the document's text. Returns how many were replaced. */
export function replaceAll(editor: Editor, find: string, replacement: string, matchCase: boolean): number {
  if (!find) return 0
  const needle = matchCase ? find : find.toLowerCase()
  const hits: { from: number; to: number }[] = []
  editor.state.doc.descendants((node, pos) => {
    if (!node.isText || !node.text) return
    const text = matchCase ? node.text : node.text.toLowerCase()
    for (let at = text.indexOf(needle); at !== -1; at = text.indexOf(needle, at + needle.length)) {
      hits.push({ from: pos + at, to: pos + at + needle.length })
    }
  })
  if (hits.length === 0) return 0
  const tr = editor.state.tr
  // Back to front, so earlier positions stay valid as the text changes length.
  for (const hit of hits.reverse()) {
    if (replacement) tr.insertText(replacement, hit.from, hit.to)
    else tr.delete(hit.from, hit.to)
  }
  editor.view.dispatch(tr)
  return hits.length
}

export function countMatches(editor: Editor, find: string, matchCase: boolean): number {
  if (!find) return 0
  const text = editor.getText()
  const hay = matchCase ? text : text.toLowerCase()
  const needle = matchCase ? find : find.toLowerCase()
  let count = 0
  for (let at = hay.indexOf(needle); at !== -1; at = hay.indexOf(needle, at + needle.length)) count++
  return count
}

export function wordCount(editor: Editor): number {
  const words = editor.getText().trim().match(/\S+/g)
  return words ? words.length : 0
}
