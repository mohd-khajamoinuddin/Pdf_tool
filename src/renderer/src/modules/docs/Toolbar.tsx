import type { Editor } from '@tiptap/react'
import type { ReactNode } from 'react'
import { Icon, type IconName } from '../../components/Icon'
import { MenuButton } from '../../components/Menu'
import { FONTS, insertPageBreak, SIZES } from './editor'

function Tool(props: { icon?: IconName; glyph?: string; label: string; active?: boolean; disabled?: boolean; onClick(): void }): ReactNode {
  return (
    <button
      className={`doc-tool${props.active ? ' active' : ''}`}
      title={props.label}
      aria-label={props.label}
      aria-pressed={props.active}
      disabled={props.disabled}
      // Keep the text selection: a toolbar click must not blur the editor first.
      onMouseDown={(e) => e.preventDefault()}
      onClick={props.onClick}
    >
      {props.icon ? <Icon name={props.icon} size={16} /> : <span className={`glyph glyph-${props.glyph}`}>{props.glyph}</span>}
    </button>
  )
}

/** The formatting ribbon. Re-rendered on every editor transaction, so its state follows the selection. */
export function Toolbar(props: { editor: Editor; onInsertImage(): void; onFind(): void }): ReactNode {
  const { editor } = props
  const chain = () => editor.chain().focus()
  const style = editor.getAttributes('textStyle') as { fontFamily?: string; fontSize?: string; color?: string }
  const level = ([1, 2, 3, 4, 5, 6] as const).find((l) => editor.isActive('heading', { level: l }))
  const inTable = editor.isActive('table')
  const size = style.fontSize ? String(parseFloat(style.fontSize)) : ''
  const highlight = (editor.getAttributes('highlight') as { color?: string }).color

  return (
    <div className="doc-ribbon" role="toolbar" aria-label="Formatting">
      <Tool icon="undo" label="Undo (Ctrl+Z)" disabled={!editor.can().undo()} onClick={() => chain().undo().run()} />
      <Tool icon="redo" label="Redo (Ctrl+Y)" disabled={!editor.can().redo()} onClick={() => chain().redo().run()} />
      <span className="sep" />

      <select
        aria-label="Paragraph style"
        className="w-style"
        value={level ? String(level) : 'p'}
        onChange={(e) => (e.target.value === 'p' ? chain().setParagraph().run() : chain().setHeading({ level: Number(e.target.value) as 1 }).run())}
      >
        <option value="p">Normal</option>
        {[1, 2, 3, 4, 5, 6].map((l) => (
          <option key={l} value={l}>
            Heading {l}
          </option>
        ))}
      </select>
      <select
        aria-label="Font"
        className="w-font"
        value={style.fontFamily ?? ''}
        onChange={(e) => (e.target.value ? chain().setFontFamily(e.target.value).run() : chain().unsetFontFamily().run())}
      >
        <option value="">Default font</option>
        {FONTS.map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
        {style.fontFamily && !FONTS.includes(style.fontFamily) && <option value={style.fontFamily}>{style.fontFamily}</option>}
      </select>
      <select
        aria-label="Font size"
        className="w-size"
        value={size}
        onChange={(e) => (e.target.value ? chain().setFontSize(`${e.target.value}pt`).run() : chain().unsetFontSize().run())}
      >
        <option value="">Size</option>
        {SIZES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
        {size && !SIZES.includes(Number(size)) && <option value={size}>{size}</option>}
      </select>
      <span className="sep" />

      <Tool glyph="B" label="Bold (Ctrl+B)" active={editor.isActive('bold')} onClick={() => chain().toggleBold().run()} />
      <Tool glyph="I" label="Italic (Ctrl+I)" active={editor.isActive('italic')} onClick={() => chain().toggleItalic().run()} />
      <Tool glyph="U" label="Underline (Ctrl+U)" active={editor.isActive('underline')} onClick={() => chain().toggleUnderline().run()} />
      <Tool glyph="S" label="Strikethrough" active={editor.isActive('strike')} onClick={() => chain().toggleStrike().run()} />
      <label className="doc-color" title="Text colour">
        <span className="glyph" style={{ borderBottomColor: style.color ?? '#111827' }}>
          A
        </span>
        <input type="color" aria-label="Text colour" value={style.color ?? '#111827'} onChange={(e) => chain().setColor(e.target.value).run()} />
      </label>
      <label className="doc-color" title="Highlight">
        <Icon name="highlighter" size={16} />
        <input
          type="color"
          aria-label="Highlight colour"
          value={highlight ?? '#fff176'}
          onChange={(e) => chain().setHighlight({ color: e.target.value }).run()}
        />
      </label>
      <Tool icon="eraser" label="Clear formatting" onClick={() => chain().unsetAllMarks().clearNodes().run()} />
      <span className="sep" />

      <Tool icon="alignLeft" label="Align left" active={editor.isActive({ textAlign: 'left' })} onClick={() => chain().setTextAlign('left').run()} />
      <Tool icon="alignCenter" label="Align centre" active={editor.isActive({ textAlign: 'center' })} onClick={() => chain().setTextAlign('center').run()} />
      <Tool icon="alignRight" label="Align right" active={editor.isActive({ textAlign: 'right' })} onClick={() => chain().setTextAlign('right').run()} />
      <Tool icon="alignJustify" label="Justify" active={editor.isActive({ textAlign: 'justify' })} onClick={() => chain().setTextAlign('justify').run()} />
      <span className="sep" />

      <Tool icon="listBullet" label="Bulleted list" active={editor.isActive('bulletList')} onClick={() => chain().toggleBulletList().run()} />
      <Tool icon="listNumber" label="Numbered list" active={editor.isActive('orderedList')} onClick={() => chain().toggleOrderedList().run()} />
      <Tool icon="outdent" label="Decrease indent" disabled={!editor.can().liftListItem('listItem')} onClick={() => chain().liftListItem('listItem').run()} />
      <Tool icon="indent" label="Increase indent" disabled={!editor.can().sinkListItem('listItem')} onClick={() => chain().sinkListItem('listItem').run()} />
      <span className="sep" />

      <MenuButton
        icon="table"
        label="Table"
        items={
          inTable
            ? [
                { label: 'Insert row above', onSelect: () => chain().addRowBefore().run() },
                { label: 'Insert row below', onSelect: () => chain().addRowAfter().run() },
                { label: 'Insert column left', onSelect: () => chain().addColumnBefore().run() },
                { label: 'Insert column right', onSelect: () => chain().addColumnAfter().run() },
                { label: 'Delete row', onSelect: () => chain().deleteRow().run() },
                { label: 'Delete column', onSelect: () => chain().deleteColumn().run() },
                { label: 'Merge or split cells', onSelect: () => chain().mergeOrSplit().run() },
                { label: 'Toggle header row', onSelect: () => chain().toggleHeaderRow().run() },
                { label: 'Delete table', onSelect: () => chain().deleteTable().run() }
              ]
            : [
                { label: 'Insert 2 × 2', onSelect: () => chain().insertTable({ rows: 2, cols: 2, withHeaderRow: false }).run() },
                { label: 'Insert 3 × 3 with header', onSelect: () => chain().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run() },
                { label: 'Insert 4 × 5 with header', onSelect: () => chain().insertTable({ rows: 4, cols: 5, withHeaderRow: true }).run() }
              ]
        }
      />
      <Tool icon="image" label="Insert image" onClick={props.onInsertImage} />
      <Tool icon="rule" label="Horizontal line" onClick={() => chain().setHorizontalRule().run()} />
      <Tool icon="pageBreak" label="Page break" onClick={() => insertPageBreak(editor)} />
      <span className="sep" />
      <Tool icon="search" label="Find and replace" onClick={props.onFind} />
    </div>
  )
}
