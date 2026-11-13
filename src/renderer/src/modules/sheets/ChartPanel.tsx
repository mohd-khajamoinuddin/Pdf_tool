import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef, type ReactNode } from 'react'
import { Icon } from '../../components/Icon'
import type { CellRange } from './univer'

echarts.use([BarChart, LineChart, PieChart, ScatterChart, GridComponent, LegendComponent, TitleComponent, TooltipComponent, CanvasRenderer])

export type ChartType = 'bar' | 'line' | 'pie' | 'scatter'

export interface ChartSpec {
  id: string
  type: ChartType
  title: string
  sheetId: string
  sheetName: string
  range: CellRange
  a1: string
}

const TYPES: { id: ChartType; label: string }[] = [
  { id: 'bar', label: 'Bar' },
  { id: 'line', label: 'Line' },
  { id: 'pie', label: 'Pie' },
  { id: 'scatter', label: 'Scatter' }
]

const PALETTE = ['#2e6fdb', '#12b76a', '#f79009', '#d92d20', '#7a5af8', '#0e9384']

const number = (text: string): number => {
  const n = Number(text.replace(/[,\s%$€£]/g, ''))
  return Number.isFinite(n) ? n : 0
}

/** First row = series names, first column = categories (x values for scatter). */
function option(type: ChartType, title: string, rows: string[][], dark: boolean): echarts.EChartsCoreOption {
  const header = rows[0] ?? []
  const body = rows.slice(1)
  const categories = body.map((r) => r[0] ?? '')
  const names = header.slice(1)
  const text = dark ? '#e7e9ee' : '#1c2128'
  const base = {
    color: PALETTE,
    backgroundColor: 'transparent',
    textStyle: { color: text },
    title: { text: title, left: 'center', textStyle: { color: text, fontSize: 14 } },
    tooltip: { trigger: type === 'pie' || type === 'scatter' ? 'item' : 'axis' },
    legend: { bottom: 0, textStyle: { color: text } },
    animation: false
  }
  if (type === 'pie') {
    return { ...base, series: [{ type: 'pie', radius: '62%', name: names[0], data: body.map((r) => ({ name: r[0], value: number(r[1] ?? '') })) }] }
  }
  const axis = { axisLabel: { color: text }, axisLine: { lineStyle: { color: text } } }
  if (type === 'scatter') {
    return {
      ...base,
      grid: { left: 48, right: 16, top: 40, bottom: 56 },
      xAxis: { type: 'value', ...axis },
      yAxis: { type: 'value', ...axis },
      series: names.map((name, i) => ({ type: 'scatter', name, data: body.map((r) => [number(r[0] ?? ''), number(r[i + 1] ?? '')]) }))
    }
  }
  return {
    ...base,
    grid: { left: 48, right: 16, top: 40, bottom: 56 },
    xAxis: { type: 'category', data: categories, ...axis },
    yAxis: { type: 'value', ...axis },
    series: names.map((name, i) => ({ type, name, data: body.map((r) => number(r[i + 1] ?? '')) }))
  }
}

function Preview({ spec, rows }: { spec: ChartSpec; rows: string[][] }): ReactNode {
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!host.current) return
    const instance = echarts.init(host.current)
    chart.current = instance
    const observer = new ResizeObserver(() => instance.resize())
    observer.observe(host.current)
    return () => {
      observer.disconnect()
      instance.dispose()
    }
  }, [])

  useEffect(() => {
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches
    chart.current?.setOption(option(spec.type, spec.title, rows, dark), true)
  }, [spec.type, spec.title, rows])

  return <div className="chart-canvas" ref={host} />
}

export function ChartPanel(props: {
  charts: ChartSpec[]
  /** Current cell text for a chart's range. */
  rowsFor(spec: ChartSpec): string[][]
  onAdd(type: ChartType): void
  onChange(spec: ChartSpec): void
  onRemove(id: string): void
  onClose(): void
}): ReactNode {
  return (
    <aside className="chart-panel" aria-label="Charts">
      <header>
        <h3>Charts</h3>
        <button className="icon-btn" aria-label="Close charts panel" onClick={props.onClose}>
          <Icon name="close" size={14} />
        </button>
      </header>
      <p className="muted small">
        Select a range whose first row holds series names and first column holds labels, then add a chart. With a single
        cell selected, the sheet&apos;s whole data range is used.
      </p>
      <div className="chart-add">
        {TYPES.map((t) => (
          <button key={t.id} className="btn" onClick={() => props.onAdd(t.id)}>
            <Icon name="plus" size={14} />
            {t.label}
          </button>
        ))}
      </div>
      {props.charts.length === 0 && <p className="muted small">No charts yet.</p>}
      {props.charts.map((spec) => (
        <section key={spec.id} className="chart-card">
          <div className="chart-head">
            <input
              aria-label="Chart title"
              value={spec.title}
              placeholder="Chart title"
              onChange={(e) => props.onChange({ ...spec, title: e.target.value })}
            />
            <select aria-label="Chart type" value={spec.type} onChange={(e) => props.onChange({ ...spec, type: e.target.value as ChartType })}>
              {TYPES.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
            <button className="icon-btn" aria-label="Remove chart" onClick={() => props.onRemove(spec.id)}>
              <Icon name="trash" size={14} />
            </button>
          </div>
          <Preview spec={spec} rows={props.rowsFor(spec)} />
          <small className="muted">
            {spec.sheetName}!{spec.a1}
          </small>
        </section>
      ))}
    </aside>
  )
}
