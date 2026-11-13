import type { ReactNode } from 'react'

// A small local icon set (24x24 stroke paths) - no icon font, no remote assets.
const PATHS = {
  home: 'M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10',
  pdf: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4',
  sheet: 'M4 5h16v14H4zM4 10h16M4 15h16M10 5v14',
  doc: 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h7M9 16h7M9 8h3',
  slides: 'M3 5h18v11H3zM12 16v4M8 20h8M7 9h6M7 12h4',
  open: 'M3 7h6l2 2h10v10H3zM3 7V5h6l2 2',
  save: 'M5 3h11l3 3v15H5zM8 3v6h7V3M8 21v-7h8v7',
  word: 'M6 3h9l4 4v14H6zM15 3v4h4M9 12l1.5 5 1.5-4 1.5 4 1.5-5',
  image: 'M4 5h16v14H4zM4 15l4-4 4 4 3-3 5 5M15 9.5a1 1 0 1 0 0-.01',
  merge: 'M7 4v5a5 5 0 0 0 5 5 5 5 0 0 1 5 5v1M17 4v5a5 5 0 0 1-2 4M14 17l3 3 3-3',
  split: 'M12 3v6M12 9l-6 6v5M12 9l6 6v5M3 17l3 3 3-3M15 17l3 3 3-3',
  lock: 'M6 11h12v9H6zM9 11V8a3 3 0 0 1 6 0v3',
  stamp: 'M9 3h6v3l-1 5h4l2 5H4l2-5h4L9 6zM4 20h16',
  plus: 'M12 5v14M5 12h14',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13',
  folder: 'M3 7h6l2 2h10v10H3z',
  close: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  alert: 'M12 4l9 16H3zM12 10v4M12 17.5v.01',
  shield: 'M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6zM9 12l2 2 4-4',
  layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5',
  text: 'M5 6h14M5 10h14M5 14h9M5 18h11',
  cursor: 'M6 3l12 9-6 1-2 6z',
  type: 'M5 6V4h14v2M12 4v16M9 20h6',
  highlighter: 'M4 20h6M14 4l6 6-9 9H5v-6z',
  pen: 'M4 20c3-1 4-4 6-7s4-7 6-7 2 3 0 6-5 5-4 7 5 1 8-1',
  square: 'M5 5h14v14H5z',
  circle: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16',
  line: 'M5 19L19 5',
  arrow: 'M5 19L19 5M10 5h9v9',
  note: 'M5 4h14v11l-5 5H5zM14 20v-5h5',
  signature: 'M3 17c3-6 5-10 7-10s0 8 2 8 2-4 4-4 1 4 5 3M3 21h18',
  redact: 'M4 8h16v8H4zM7 12h10',
  undo: 'M9 7L4 12l5 5M4 12h10a6 6 0 0 1 0 12',
  redo: 'M15 7l5 5-5 5M20 12H10a6 6 0 0 0 0 12',
  rotate: 'M20 12a8 8 0 1 1-3-6.2M20 4v5h-5',
  up: 'M12 19V5M6 11l6-6 6 6',
  down: 'M12 5v14M6 13l6 6 6-6',
  zoomIn: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14M16 16l5 5M8 11h6M11 8v6',
  zoomOut: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14M16 16l5 5M8 11h6',
  chevron: 'M6 9l6 6 6-6',
  table: 'M4 5h16v14H4zM4 10h16M9 5v14',
  code: 'M9 7l-5 5 5 5M15 7l5 5-5 5',
  alignLeft: 'M4 6h16M4 10h10M4 14h16M4 18h10',
  alignCenter: 'M4 6h16M7 10h10M4 14h16M7 18h10',
  alignRight: 'M4 6h16M10 10h10M4 14h16M10 18h10',
  alignJustify: 'M4 6h16M4 10h16M4 14h16M4 18h16',
  listBullet: 'M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01',
  listNumber: 'M10 6h10M10 12h10M10 18h10M4 5l1.5-1v4M4 11h2l-2 3h2M4 17h2v3H4',
  indent: 'M4 6h16M11 10h9M11 14h9M4 18h16M4 10l3 2-3 2',
  outdent: 'M4 6h16M11 10h9M11 14h9M4 18h16M7 10l-3 2 3 2',
  rule: 'M4 12h16',
  pageBreak: 'M6 3v5h12V3M6 21v-5h12v5M3 12h2M8 12h2M14 12h2M19 12h2',
  eraser: 'M8 20h12M5 15l9-9 5 5-8 8H8z',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14M16 16l5 5',
  mail: 'M3 6h18v12H3zM3 7l9 6 9-6',
  play: 'M7 4l13 8-13 8z',
  copy: 'M9 9h11v11H9zM5 15V4h11',
  triangle: 'M12 4l9 16H3z',
  front: 'M8 8h12v12H8zM4 16V4h12',
  back: 'M4 4h12v12H4zM8 20h12V8',
  palette: 'M12 3a9 9 0 1 0 0 18c1.5 0 2-1 2-2s-.5-1.5-.5-2.5S14.5 15 16 15h2a3 3 0 0 0 3-3c0-5-4-9-9-9M7.5 11h.01M10.5 7.5h.01M15 8h.01'
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 18 }: { name: IconName; size?: number }): ReactNode {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
