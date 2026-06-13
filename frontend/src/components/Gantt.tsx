// Lightweight SVG Gantt for the schedule section. Bars are positioned along a
// day axis; the critical path is drawn in red (SPEC 5.2). No chart library.
// Rows are clickable when onSelect is provided (the schedule editor).

export interface GanttNode {
  start: number
  end: number
  critical: boolean
  name?: string
  start_date?: string
  end_date?: string
}

const LABEL_W = 200
const CHART_W = 540
const ROW_H = 28
const BAR_H = 15
const AXIS_H = 26
const PAD = 12

export default function Gantt({
  nodes,
  totalDays,
  selected,
  onSelect,
}: {
  nodes: Record<string, GanttNode>
  totalDays: number
  selected?: string | null
  onSelect?: (id: string) => void
}) {
  const rows = Object.entries(nodes)
    .map(([id, n]) => ({ id, ...n }))
    .sort((a, b) => a.start - b.start || a.end - b.end)

  const span = totalDays || 1
  const dayX = (d: number) => LABEL_W + (d / span) * CHART_W
  const height = AXIS_H + rows.length * ROW_H + PAD
  const width = LABEL_W + CHART_W + PAD

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * span))

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="График по възли">
      {/* axis gridlines + day labels */}
      {ticks.map((d) => (
        <g key={d}>
          <line x1={dayX(d)} y1={AXIS_H - 6} x2={dayX(d)} y2={height - PAD} stroke="var(--border)" />
          <text x={dayX(d)} y={14} fontSize="11" fill="var(--muted)" textAnchor="middle">
            {d} дни
          </text>
        </g>
      ))}

      {rows.map((r, i) => {
        const y = AXIS_H + i * ROW_H
        const x = dayX(r.start)
        const w = Math.max(2, dayX(r.end) - x)
        const label = r.name ?? r.id
        const isSel = selected === r.id
        return (
          <g
            key={r.id}
            onClick={onSelect ? () => onSelect(r.id) : undefined}
            style={onSelect ? { cursor: 'pointer' } : undefined}
          >
            {isSel && (
              <rect x={0} y={y} width={width - PAD} height={ROW_H} fill="var(--amber-soft)" rx={4} />
            )}
            <text x={0} y={y + ROW_H / 2 + 4} fontSize="12" fill="var(--text)">
              {label.length > 30 ? label.slice(0, 29) + '…' : label}
            </text>
            <rect
              x={x}
              y={y + (ROW_H - BAR_H) / 2}
              width={w}
              height={BAR_H}
              rx={3}
              fill={r.critical ? 'var(--red)' : 'var(--navy)'}
              stroke={isSel ? 'var(--amber)' : 'none'}
              strokeWidth={isSel ? 2 : 0}
            >
              <title>{`${label}: ден ${r.start}–${r.end}${r.start_date ? ` (${r.start_date} – ${r.end_date})` : ''}${r.critical ? ' · критичен' : ''}`}</title>
            </rect>
          </g>
        )
      })}
    </svg>
  )
}
