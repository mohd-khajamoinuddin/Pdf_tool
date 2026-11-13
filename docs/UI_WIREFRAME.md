# DocSuite — UI / UX Concept

The layout below is implemented in `src/renderer`. Screenshots in `docs/screenshots/` were captured from the running app by `scripts/smoke.cjs`.

## 1. Principles

1. **One shell, four workspaces.** Navigation, toolbar position, job feedback and dialogs are identical everywhere; only the canvas changes.
2. **Colour tells you where you are.** Each workspace has one accent (PDF red, Spreadsheets green, Documents blue, Slides orange) applied to its nav item, primary button, file chip and selection.
3. **Privacy is visible, not buried.** A permanent "Offline by design" note in the sidebar and "Network access disabled" in the status bar.
4. **Nothing destructive by default.** Every operation writes a new file through a Save dialog; the app refuses to save a lossy rewrite over the original.
5. **Long work never blocks.** Conversions run as jobs with progress in a tray; you can keep working or switch workspace.
6. **Honest about limits.** Where an editor is partial, a notice strip says exactly what is and is not preserved.

## 2. Shell

```
┌────────────┬───────────────────────────────────────────────────────────────┐
│ ▣ DocSuite │  Workspace title   [ file-name.pdf · edited ]                 │
│            │  [Open] │ [Action] [Action] [Action] │ [Action] [Action]      │
│ ⌂ Home     ├───────────────────────────────────────────────────────────────┤
│ ▤ PDF      │  (optional notice strip: what this build does not preserve)   │
│ ▦ Sheets   ├───────────────────────────────────────────────────────────────┤
│ ▥ Docs     │                                                               │
│ ▧ Slides   │                       workspace canvas                        │
│            │                                                               │
│            │                                          ┌──────────────────┐ │
│ ┌────────┐ │                                          │ ✓ a.pdf → Word   │ │
│ │🛡 Offline│ │                                          │ Show in folder   │ │
│ │ by design│ │                                          └──────────────────┘ │
│ └────────┘ │                                              job tray (toasts) │
├────────────┴───────────────────────────────────────────────────────────────┤
│ ● Processing engine ready                         🛡 Network access disabled │
└────────────────────────────────────────────────────────────────────────────┘
```

- **Sidebar (216 px):** brand, five destinations, privacy note pinned to the bottom.
- **Header + toolbar:** title, file chip, then actions grouped by intent with separators. The one primary (filled) button is always the next sensible step — "Open" when nothing is loaded.
- **Job tray:** bottom-right, newest first, max six. Running jobs show a progress bar and the engine's message ("page 4/10"); finished jobs offer "Show in folder"; failures show the engine's error text.
- **Status bar:** engine state (starting / ready / stopped with reason) and the network statement.
- **Workspaces stay mounted** when you switch, so an open file and unsaved edits are still there when you come back.

## 3. Home (unified dashboard)

Four workspace cards and a row of quick actions (PDF to Word, Merge PDFs, Images to PDF, …) that run straight from Home: pick file → pick destination → job. See `screenshots/core-home.png`.

*Planned:* a "Recent files" row. It needs a main-process store, because a path remembered by the UI is not usable until the user re-grants it (see the path allow-list in `ARCHITECTURE.md` §5).

## 4. PDF Studio — `screenshots/pdf-annotated.png`, `pdf-saved.png`

```
 [Open] [Save as…] │ [Convert ▾] [Split] [Merge…] │ [Watermark] [Protect]
 ▸ T ✎ ~ ▢ ◯ ╱ ↗ ▤ ▬ │ Signature  Image │ ● ● ● ● ● ● ● │ Line 2pt  Text 14pt │ ↶ ↷ │ − 100% +
┌──────────┬──────────────────────────────────────────────┬──────────────────┐
│ ┌──────┐ │                                              │ DOCUMENT         │
│ │ pg 1 │②│            ┌────────────────────┐            │ Pages, size, …   │
│ └──────┘ │            │  page + overlay    │            │                  │
│ 1 ↑↓⟳🗑  │            │  (drawn in points) │            │ PAGE 1 OF 3      │
│ ┌──────┐ │            └────────────────────┘            │ [Previous][Next] │
│ │ pg 2 │ │                                              │ SELECTION        │
│ └──────┘ │                                              │ [Delete]         │
└──────────┴──────────────────────────────────────────────┴──────────────────┘
  organiser             canvas                              inspector
```

- **Organiser:** drag a thumbnail to reorder; hover buttons move, rotate and delete; a badge counts annotations on the page.
- **Tools row:** select, text, highlight, draw, rectangle, ellipse, line, arrow, note, redact; then signature and image stamps, colour, line width, text size, undo/redo, zoom.
- **Canvas:** an SVG overlay in PDF points sits on the rendered page, so what is drawn is exactly what is saved. Select to move, resize (corner handle) or restyle; double-click text to edit.
- **Save as…** writes a new file and continues on it; conversions refuse to run while there are unsaved edits, because they read the file on disk.
- A notice appears as soon as a redaction box exists, explaining that it is permanent and what it does not scrub.

## 5. Spreadsheets — `screenshots/sheets-edited.png`

The workspace hosts the Univer grid (its own ribbon, formula bar, sheet tabs and zoom) under the suite's toolbar: New, Open, Save as…, Charts, Export PDF. The Charts button opens a side panel: choose a type, and the selection (or the sheet's data range) becomes a live preview that follows edits.

## 6. Documents — `screenshots/docs-gallery.png`, `docs-merge.png`

```
 [New ▾] [Open] [Save as…] │ [Header & footer] [Mail merge] [Export PDF]
 ↶ ↷ │ Normal ▾  Font ▾  Size ▾ │ B I U S A 🖍 ⌫ │ ≡ ≡ ≡ ≡ │ • 1. ⇤ ⇥ │ Table ▾ 🖼 ─ ⤓ │ 🔍
┌────────────────────────────────────────────────────────┬──────────────────┐
│        ┌──────────────────────────────────┐            │ MAIL MERGE       │
│        │  page on a neutral canvas        │            │ {{name}}  Ada    │
│        │  WYSIWYG content                 │            │ {{city}}  London │
│        └──────────────────────────────────┘            │ [Generate…]      │
└────────────────────────────────────────────────────────┴──────────────────┘
  6 words
```

An empty workspace shows the template gallery. The ribbon reflects the formatting at the cursor. The Table menu changes with context (insert sizes outside a table; row, column, merge and header actions inside one). The mail-merge panel shows each field with a sample value from the first record.

## 7. Slides — `screenshots/slides-editing.png`, `slides-show.png`

```
 [New ▾] [Open] [Save as…] │ [Text] [Shape ▾] [Image] │ [Undo] [Redo] │ [Present] [Export ▾]
┌─────────────┬──────────────────────────────────────────┬──────────────────┐
│ 1 ┌───────┐ │                                          │ TEXT / SHAPE     │
│   │ thumb │ │   ┌──────────────────────────────────┐   │ font, size, …    │
│   └───────┘ │   │  slide, zoomed to fit            │   │ POSITION         │
│ 2 ┌───────┐ │   │  handles: move, resize, rotate   │   │ X  Y  W  H  °    │
│   │ thumb │ │   └──────────────────────────────────┘   │ ARRANGE          │
│   └───────┘ │   Speaker notes [____________________]   │ align · order    │
│ [+ Slide] … │                                          │ duplicate·delete │
└─────────────┴──────────────────────────────────────────┴──────────────────┘
  filmstrip                 stage + notes                    inspector
```

An empty workspace shows the theme gallery. Thumbnails are real renders of each slide and are also the source for image and PDF export. With nothing selected the inspector shows slide properties (background, transition, speed) and deck properties (theme, slide size). Present runs full screen: arrows, space or click advance; Esc exits.

## 8. Shared patterns

| Pattern | Behaviour |
|---|---|
| Empty state | PDF: icon, one sentence, primary "Open". Documents and Slides: a gallery of templates / themes. Spreadsheets: Open or New workbook |
| Prompt dialog | In-app modal (split ranges, watermark text, passwords). Enter confirms, Escape or backdrop cancels, first field focused |
| Errors | Shown where the action was reported (job tray), using the engine's message; never a raw stack trace |
| Theme | Follows the OS light/dark setting; document pages stay white in dark mode because they represent paper |
| Keyboard | Everything is a native button/input with visible focus rings; reduced-motion preference is respected |

Not yet verified: screen-reader pass, high-contrast mode, window widths under 980 px (the minimum window size is set to 980 × 620).
