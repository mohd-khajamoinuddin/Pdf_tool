# DocSuite — Tech Stack Selection

How to read this document:

- **Verified** = installed in this repository; version and licence read from the installed package metadata, and the capability exercised by a passing test.
- **Recommended, not adopted** = my assessment from prior knowledge of the library. Licence and maintenance status **must be re-checked** against the project's own repository before adoption.

This is engineering input, not legal advice. Have licence conclusions reviewed by whoever owns open-source compliance before distribution.

## 1. Decisions at a glance

| Area | Choice | Status |
|---|---|---|
| Desktop shell | Electron 45 | Verified |
| UI | React 19 + TypeScript 7, built with electron-vite 6 / Vite 8 | Verified |
| Processing core | Python 3.11 child process, JSON over stdio | Verified |
| Spreadsheet editor | Univer 1.4 (open-source presets only) | Verified |
| Spreadsheet charts | Apache ECharts 6 (preview) + openpyxl charts (in the file) | Verified |
| Word processor | TipTap 3 (ProseMirror) | Verified |
| Slide canvas | Konva 10 + react-konva 19 | Verified |
| PDF read / structure / render / write | pypdf, pdfplumber, pypdfium2, reportlab | Verified |
| Office file formats | python-docx, openpyxl, python-pptx, xlrd, odfpy, striprtf | Verified |
| Certificate signing | pyHanko 0.38 | Verified |
| Packaging | PyInstaller (engine) + electron-builder (NSIS installer) | Verified on Windows |
| Layout-faithful Office ↔ PDF | LibreOffice headless, optional component | Recommended, not adopted |
| OCR | Tesseract with bundled language data | Recommended, not adopted |

## 2. Shell: Electron, not Tauri

The brief allows either. Electron was chosen:

- **It could be built and verified on the development machine**, which has Node and Python but no Rust toolchain or MSVC build tools (Tauri needs both).
- **One rendering engine on all three operating systems.** Tauri uses the system webview (WebView2 / WKWebView / WebKitGTK). This product is rendering-sensitive — a canvas spreadsheet, a rich-text editor, a slide canvas, PDF overlays — and three engines mean three sets of layout and input bugs.
- **The heavy work is in Python either way**, so Tauri's Rust core would mostly sit idle.

Cost: roughly 100 MB+ of installer and a higher idle memory floor than Tauri. The boundary is clean — the renderer only knows `window.suite` (`src/shared/api.ts`) — so the shell could be swapped later without touching the editors or the engine.

## 3. Why build on editor components instead of embedding an office suite

To get "edit, read, write and design like WPS" there are two routes:

| | Embed a complete suite (ONLYOFFICE, Collabora/LibreOffice) | Compose editor components (this build) |
|---|---|---|
| Fidelity with existing Office files | High from day one | Partial; grows feature by feature |
| Licence | ONLYOFFICE is AGPL-3.0 to my knowledge; Collabora/LibreOffice is MPL-2.0 | Apache-2.0 / MIT / BSD throughout |
| Size and integration | Several hundred MB; runs as its own local server or native process | About 17 MB of JavaScript, in-process |
| Control over UI and offline guarantees | Their UI, their update and network behaviour to audit | Ours |

This build takes the component route because every shipped part stays permissively licensed and under the app's own offline controls. **If near-perfect fidelity with arbitrary Office files is the product's main promise, the embed route (most plausibly LibreOffice/Collabora under MPL-2.0) is the faster way there**, at the cost of size and a heavier integration. That is a product decision; see §5.

## 4. Verified libraries

### JavaScript (shipped in the app)

| Library | Version | Licence | Used for |
|---|---|---|---|
| electron | 45.3.0 | MIT | desktop shell |
| react, react-dom | 19.3.1 | MIT | UI |
| @univerjs/presets + preset-sheets-core, -filter, -sort, -find-replace, -conditional-formatting, -data-validation | 1.4.0 | Apache-2.0 | spreadsheet grid, formula engine, formatting, sort/filter |
| echarts | 6.1.0 | Apache-2.0 | chart previews |
| @tiptap/react, pm, starter-kit, extension-table, -image, -text-align, -text-style, -highlight | 3.33.1 | MIT | word processor |
| konva, react-konva | 10.9.1, 19.3.2 | MIT | slide canvas and slide show rendering |

Build-time only: electron-vite 6.0.0 (MIT), vite 8.3.8 (MIT), typescript 7.0.2 (Apache-2.0), @vitejs/plugin-react 6.3.0 (MIT), electron-builder 26.18.0 (MIT), PyInstaller 6.22.3 (GPL-2.0-or-later with a special exception allowing it to build programs under any licence; it is a build tool and is not shipped).

Univer also publishes paid "Pro" packages (native xlsx import/export, built-in charts, pivot tables, printing). **None is used.** File import/export and charts are implemented in this repository instead (`engine/…/handlers/workbook.py`, `ChartPanel.tsx`).

### Python (the processing engine)

| Library | Version | Licence | Used for |
|---|---|---|---|
| pypdf | 7.0.1 | BSD-3-Clause | page organise, merge/split, AES-256 encryption, permissions, annotations |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | AES backend for pypdf |
| pdfplumber (+ pdfminer.six) | 0.11.10 | MIT | text with fonts, table detection |
| pypdfium2 | 5.15.2 | BSD-3-Clause / Apache-2.0 (+ PDFium's own licences) | page rendering, redaction raster |
| reportlab | 5.1.0 | BSD | PDF generation, annotation overlays |
| Pillow | 13.0.0 | MIT-CMU | image I/O |
| python-docx | 1.2.0 | MIT | .docx read/write |
| openpyxl | 3.1.5 | MIT | .xlsx read/write, native charts |
| python-pptx | 1.0.2 | MIT | .pptx read/write |
| lxml | 6.1.3 | BSD-3-Clause | XML for the Office formats |
| xlrd | 2.0.2 | BSD | read legacy .xls |
| odfpy | 1.4.1 | Apache-2.0 (also offered under GPL / LGPL) | read .odt |
| striprtf | 0.0.35 | BSD-3-Clause | read .rtf text |
| pyHanko (+ pyhanko-certvalidator, asn1crypto, oscrypto, tzlocal) | 0.38.1 | MIT | PDF digital signatures |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT | installed by pyHanko for timestamp/revocation lookups; never invoked here |
| tzdata | 2026.6 | Apache-2.0 | time-zone data on Windows |

Nothing copyleft-only is linked into the product. `odfpy` is multi-licensed; the Apache-2.0 option is the one relied on.

## 5. Decisions that still need your input

### 5.1 PyMuPDF / pdf2docx — excluded on licence grounds

The brief suggests `PyMuPDF`. To my knowledge it is AGPL-3.0 or commercial (Artifex); shipping it in a closed-source product needs one or the other. *Not installed, so not verified from metadata.* The implemented alternative is a pdfplumber + python-docx reconstruction.

| | Implemented (permissive stack) | PyMuPDF / pdf2docx |
|---|---|---|
| Headings, paragraphs, bold/italic, ruled tables, images | Yes (tested) | Yes |
| Multi-column pages | Read across columns — wrong order | Handled |
| Borderless tables, text boxes, vector graphics | Missed or dropped | Often preserved |
| Editing existing PDF text in place | Line by line, with a standard font of the same family | Reflowing paragraphs, original embedded fonts |
| Redaction | Done here by rasterising the page | Built in, keeps the rest of the page as text |

**Recommendation:** stay permissive, and buy a commercial PyMuPDF licence only if real customer PDFs show the gaps matter. The converter registry lets it be added as a second backend.

### 5.2 LibreOffice as an optional component

No pure-Python or JavaScript library lays out a document the way Word, Excel or PowerPoint do. LibreOffice headless (MPL-2.0 to my knowledge) would add: layout-faithful Office → PDF, real `.odt` / `.rtf` / `.xls` / `.odp` import and export, and slide rendering identical to PowerPoint's. Cost: roughly 300–400 MB and a slow first conversion.

**Recommendation:** ship it as an optional component the app detects and registers as a `libreoffice` converter backend.

### 5.3 What "like WPS" means for the roadmap

The editors now cover everyday creation and editing. The remaining distance to WPS is mostly **import fidelity** and **depth of features**, and it is large — WPS and Office are the product of very many engineer-years. Two honest options:

1. **Keep composing** (current path): pick the gaps that matter to your users and close them one at a time — for example text runs with mixed formatting in slides, tables in slides, paginated layout in documents, reading charts and conditional formatting back from `.xlsx`.
2. **Embed LibreOffice/Collabora for editing**, keep this shell, PDF Studio and the offline controls around it. Highest fidelity soonest; biggest install; least control over the editing UI.

Tell me which promise matters more — clean licensing and a light app, or fidelity with arbitrary Office files — and I will plan accordingly.

### 5.4 PDF features not built

| Feature | Recommended approach | Caveat |
|---|---|---|
| OCR for scanned PDFs | Tesseract (Apache-2.0 to my knowledge) with bundled language data | 15–50 MB per language |

Already built and worth knowing the limits of: **certificate signing** uses the computer's clock rather than a trusted timestamp, and verification reports integrity only, not whether the certificate is trusted or revoked — both would need a network or a managed trust store, which is a policy decision for you; the **drawn signature** tool places a picture, which is not a cryptographic signature; **permissions** (no-print, no-copy) are a request to PDF readers, not a lock; **redaction** removes page content but does not scrub bookmarks or document metadata.

## 6. Coverage against the brief

| Requirement | State |
|---|---|
| **PDF** → Word, Excel, Images, HTML, Markdown | Done, tested |
| Word, Excel, Images, Markdown → PDF | Done at content fidelity; layout fidelity needs §5.2 |
| Text editing (existing text, line by line), redaction, annotations, e-signature (drawn), watermark, reorder, split, merge | Done, tested |
| Password protection and permissions | Done, tested |
| Certificate-based signing | Done, tested with a self-signed certificate (no trusted timestamp, no trust/revocation check) |
| **Spreadsheet** read/write `.xlsx`, `.csv` | Done, tested |
| `.xls` | Read only (values) |
| Grid editing, formulas (math, logical, financial via Univer), filter, sort | Done; live calculation verified end to end |
| Charts: bar, line, pie, scatter | Done; written to `.xlsx`, not read back |
| **Word processor** `.docx`, `.txt` | Done, tested |
| `.odt` | Read and write with formatting, lists, tables, images (direct formatting only) |
| `.rtf` | Write with formatting, tables, images; read as text |
| Headings, tables, lists, images | Done, tested |
| Headers / footers | Plain text, saved to `.docx` |
| Templates | Six built in |
| Mail merge from CSV / Excel | Done, tested |
| **Presentation** `.pptx` create and edit | Done, tested |
| `.odp` | Read and write: text, shapes, images, backgrounds, notes (no rotation, transitions or bullets) |
| Local themes, image and shape insertion, transitions | Done, tested |
| Export to PDF or image sequence | Done (PDF is image-based) |
| Offline, zero telemetry, zero network | Done, verified by the smoke test |
| Batch processing | `convert.batch` and mail merge; UI for batch PDF → Word |
| Fast start-up | Editors load on first use; initial bundle about 0.6 MB. Not benchmarked. |
| Cross-platform installers | Windows installer built (unsigned); macOS and Linux not built or tested |
