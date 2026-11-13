# DocSuite

A local-first, fully offline desktop document suite: PDF editing, spreadsheets, a word processor and a slide designer in one app. Nothing leaves the machine — no telemetry, no cloud APIs, and outbound network requests are blocked at four layers.

**Status: phase 2 (working editors, Windows installer).** All four workspaces read, edit, design and write real files, and the app packages into a self-contained Windows installer. This is not yet at the level of WPS or Microsoft Office — see "Known limits" below and the requirement table in [docs/TECH_STACK.md](docs/TECH_STACK.md) §6 for exactly where it stops.

## Documents

| Deliverable | Where |
|---|---|
| System architecture diagram | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Tech stack selection and justification | [docs/TECH_STACK.md](docs/TECH_STACK.md) |
| Code | `src/` (desktop shell and UI), `engine/` (processing engine) |
| UI/UX concept | [docs/UI_WIREFRAME.md](docs/UI_WIREFRAME.md), screenshots in `docs/screenshots/` |

## What works today

**PDF Studio**
- Edit existing text: click a line to change or delete it. The original is removed from the file and the new text drawn in its place, keeping size, colour, weight and a matching standard font.
- Organise pages: reorder (drag or arrows), rotate, delete.
- Annotate: text, highlight, freehand drawing, rectangle, ellipse, line, arrow, sticky note; move, resize, restyle, undo/redo.
- Place an image or a drawn signature.
- Redact: the page is rasterised and the boxes burned in, so the text underneath is gone, not hidden.
- Convert to Word, Excel, HTML, Markdown, text or images; convert Word, Excel, CSV, text, Markdown and images to PDF; batch PDF → Word.
- Merge, split, watermark, AES-256 password protection with print/copy/edit permissions.
- Digitally sign with a local certificate (`.p12` / `.pfx`), with an optional visible stamp; existing signatures are listed and checked for integrity when a PDF is opened.

**Spreadsheets** (Univer grid)
- Live formulas, formula bar, number formats, fonts, colours, borders, alignment, merged cells, freeze panes, multiple sheets, undo/redo, copy/paste, find and replace, sort, filter, conditional formatting, data validation.
- Charts (bar, line, pie, scatter) previewed in the app and written into the `.xlsx` as native Excel charts.
- Reads `.xlsx`, `.xlsm`, `.xls`, `.csv`, `.tsv`; writes `.xlsx`, `.csv`, `.tsv`. Styles, merges, column widths, row heights and freeze panes round-trip through `.xlsx`.

**Documents** (TipTap editor)
- WYSIWYG page: headings, fonts, sizes, bold/italic/underline/strike, text and highlight colour, alignment, nested bulleted and numbered lists, tables with merged cells, images (resizable), horizontal rules, page breaks, undo/redo, find and replace, word count.
- Six built-in templates; header and footer text.
- Mail merge from a `.csv` or `.xlsx`: insert `{{field}}` placeholders, generate one document per record or one combined document.
- Reads `.docx`, `.odt`, `.md`, `.txt` with formatting and `.rtf` as text; writes `.docx`, `.odt`, `.rtf`, `.md`, `.txt`; exports PDF through Chromium's print engine.

**Slides** (Konva canvas)
- Free-position text boxes, six shape types, images; move, resize, rotate, multi-select, align, z-order, duplicate, copy/paste, arrow-key nudge, undo/redo.
- Six themes, 16:9 and 4:3, per-slide background, speaker notes, slide reordering.
- Per-slide transitions, shown in the full-screen slide show and written into the `.pptx`.
- Reads and writes `.pptx` and `.odp`; exports PDF and a PNG per slide.

## Run it

Requirements: Node 20+, Python 3.11+. (Developed and tested on Windows 11 only; macOS and Linux are untested.)

```powershell
npm install
npm run engine:setup     # creates engine/.venv and installs the Python libraries
npm run dev              # launches the app with hot reload
```

`npm install` and `engine:setup` download packages and the Electron binary; the app itself never uses the network.

## Test it

```powershell
npm run engine:test      # 54 pytest tests against the processing engine
npm run typecheck
npm run smoke            # builds, launches the real app and drives every workspace (91 checks)
```

`npm run smoke` stubs only the native file dialogs. It uses real mouse and keyboard input, saves files, and verifies them by reading them back. To run one workspace: `npx electron -r ./scripts/smoke.cjs . .smoke --only=core,slides`.

## Build the Windows installer

```powershell
npm run dist             # freezes the engine, builds the app, writes dist\DocSuite Setup <version>.exe
npm run pack             # same without the installer step: dist\win-unpacked\DocSuite.exe
```

The installer is about 155 MB and contains everything, including the Python engine as a frozen program — the target machine needs neither Python nor Node. Building it downloads NSIS and an Electron archive once; the result is offline.

What was checked on the packaged build: it starts, launches its bundled engine, and holds no TCP or UDP sockets. The full end-to-end suite was run against the frozen engine. Not done: the installer is **not code-signed** (Windows SmartScreen will warn), it uses the default Electron icon, and the install/uninstall flow itself has not been run.

## Layout

```
src/shared/api.ts          the only surface the UI can call (window.suite)
src/main/                  Electron main: window, network lockdown, IPC, engine process
src/preload/               contextBridge
src/renderer/src/          React UI
  modules/PdfStudio.tsx    + modules/pdf/      page canvas, edit model, signature pad
  modules/Sheets.tsx       + modules/sheets/   Univer wrapper, chart panel
  modules/Documents.tsx    + modules/docs/     TipTap setup, ribbon, templates
  modules/Slides.tsx       + modules/slides/   deck model, stage, inspector, slide show
engine/docsuite_engine/    Python engine: rpc.py, handlers/, convert/
engine/tests/              pytest
scripts/                   smoke.cjs + smoke/<workspace>.cjs, make_samples.py
```

## Known limits

These are the gaps between this build and a mature office suite. None of them is hidden by the app: where content cannot be imported, the workspace says what was left out, and it refuses to save over a file it did not write.

- **Fidelity with existing Office files is partial.** Opening a complex Word, Excel or PowerPoint file keeps what the editor models and reports the rest (for example footnotes, text boxes, SmartArt, pivot tables, master-slide artwork). Simple to moderately formatted files round-trip well; heavily designed ones will look different.
- **Slides:** one format per text box (mixed bold/colour inside a box is flattened); no tables, charts, animations or snapping guides; only six shapes; theme and master artwork of an opened deck are not carried over; PDF export is image-based, so its text is not selectable. `.odp` does not store rotation, transitions, bullets or arrow heads, and has not been opened in LibreOffice to confirm how it renders there.
- **Documents:** no true page layout on screen (the page is one continuous sheet; page breaks apply on export), no footnotes, comments, tracked changes, columns or section layouts; `.rtf` opens as text only and is written with lists as indented text; `.odt` keeps direct formatting but not formatting inherited from named styles, and has not been opened in LibreOffice to confirm how it renders there; header and footer are saved to `.docx` only.
- **Spreadsheets:** charts, conditional formatting and data validation are not read back from an opened `.xlsx` (charts are written, the other two are session-only); no pivot tables or images; files above 400 000 cells are loaded partially and cannot be saved; `.xls` opens values-only.
- **PDF:** text is edited one line (or table cell) at a time, not as reflowing paragraphs, so a longer replacement can run past its neighbours; the replacement uses a standard font of the same family (sans, serif or mono), not the document's embedded font, so its shape can differ slightly; text on rotated pages and in scanned (image) pages cannot be edited; when a line cannot be removed cleanly it is painted over instead and the save says so; existing images and drawings in a PDF cannot be selected or moved. PDF → Word reconstructs structure rather than exact layout and reads multi-column pages across columns; no OCR for scanned PDFs; redaction does not scrub bookmarks or metadata. Digital signatures use this computer's clock (no trusted timestamp), and verification checks integrity only — whether a signer's certificate is trusted or revoked is not checked, because that needs a trust store and usually a network. Signing was tested with a self-signed certificate only, not with one from a commercial authority or a hardware token.
- **Office → PDF** from the PDF Studio converters is content-faithful, not layout-faithful (see TECH_STACK §5.2).
- Windows only so far: the macOS and Linux builds have not been made or tested, and the Windows installer is unsigned.
