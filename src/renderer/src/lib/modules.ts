import type { IconName } from '../components/Icon'

export type ModuleId = 'home' | 'pdf' | 'sheets' | 'docs' | 'slides'

export const MODULES: { id: ModuleId; label: string; icon: IconName; blurb: string }[] = [
  { id: 'home', label: 'Home', icon: 'home', blurb: '' },
  { id: 'pdf', label: 'PDF Studio', icon: 'pdf', blurb: 'Edit pages, annotate, sign, redact, convert and protect PDFs.' },
  { id: 'sheets', label: 'Spreadsheets', icon: 'sheet', blurb: 'Full grid with formulas, formatting, filters and charts.' },
  { id: 'docs', label: 'Documents', icon: 'doc', blurb: 'Write and format documents, templates and mail merge.' },
  { id: 'slides', label: 'Slides', icon: 'slides', blurb: 'Design slides with themes, shapes, images and transitions.' }
]
