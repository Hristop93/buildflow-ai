// Cashflow chart for the economics section: yearly free cash flow as bars and
// the cumulative cash position as a line. Where the line crosses zero is the
// payback point.
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer,
} from 'recharts'
import type { CashflowPoint } from '../api'

const NAVY = '#1f4e78'
const AMBER = '#c55a11'

const compact = (n: number) =>
  Math.abs(n) >= 1_000_000 ? (n / 1_000_000).toFixed(1) + 'M' : Math.round(n / 1000) + 'k'

export default function CashflowChart({ data }: { data: CashflowPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e1e6ec" />
        <XAxis dataKey="year" tick={{ fontSize: 12 }} label={{ value: 'година', position: 'insideBottom', offset: -2, fontSize: 12 }} />
        <YAxis tickFormatter={compact} tick={{ fontSize: 12 }} width={48} />
        <Tooltip
          formatter={(value, name) => [
            Number(value).toLocaleString('bg-BG', { maximumFractionDigits: 0 }) + ' лв',
            name === 'fcf' ? 'Годишен поток' : 'Натрупано',
          ]}
          labelFormatter={(y) => `Година ${y}`}
        />
        <ReferenceLine y={0} stroke="#647082" />
        <Bar dataKey="fcf" fill={AMBER} name="fcf" radius={[2, 2, 0, 0]} />
        <Line type="monotone" dataKey="cumulative" stroke={NAVY} strokeWidth={2} dot={false} name="cumulative" />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
