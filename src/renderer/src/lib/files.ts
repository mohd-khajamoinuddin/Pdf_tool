import type { FileFilter } from '../../../shared/api'

export const FILTERS = {
  pdf: [{ name: 'PDF', extensions: ['pdf'] }],
  docx: [{ name: 'Word document', extensions: ['docx'] }],
  markdown: [{ name: 'Markdown', extensions: ['md'] }],
  xlsx: [{ name: 'Excel workbook', extensions: ['xlsx'] }],
  html: [{ name: 'Web page', extensions: ['html'] }],
  text: [{ name: 'Plain text', extensions: ['txt'] }],
  certificate: [{ name: 'Certificate with private key (PKCS#12)', extensions: ['p12', 'pfx'] }],
  sheetOpen: [{ name: 'Spreadsheets', extensions: ['xlsx', 'xlsm', 'csv', 'tsv'] }],
  sheetSave: [
    { name: 'Excel workbook', extensions: ['xlsx'] },
    { name: 'CSV (first sheet only)', extensions: ['csv'] }
  ],
  docOpen: [{ name: 'Documents', extensions: ['docx', 'txt', 'md'] }],
  docSave: [
    { name: 'Word document', extensions: ['docx'] },
    { name: 'Plain text', extensions: ['txt'] }
  ],
  slides: [{ name: 'PowerPoint presentation', extensions: ['pptx'] }],
  images: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'bmp', 'tiff', 'gif', 'webp'] }]
} satisfies Record<string, FileFilter[]>

export function baseName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path
}

export function withExt(path: string, ext: string, suffix = ''): string {
  return path.replace(/\.[^./\\]+$/, '') + suffix + '.' + ext
}

export function samePath(a: string, b: string): boolean {
  const norm = (p: string): string => p.replace(/\\/g, '/').toLowerCase()
  return norm(a) === norm(b)
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
