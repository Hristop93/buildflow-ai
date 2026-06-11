// Monte Carlo IRR distribution: bars per IRR bucket, with the hurdle rate as a
// red reference line. Buckets at/above the hurdle are amber, below are grey.
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer,
} from 'recharts'

interface Bucket { irr: number; count: number }

const pct = (x: number) => (x * 100).toFixed(0) + '%'

export default function RiskHistogram({ data, hurdle }: { data: Bucket[]; hurdle: number }) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 16, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e1e6ec" />
        <XAxis
          dataKey="irr"
          tickFormatter={pct}
          tick={{ fontSize: 12 }}
          label={{ value: 'IRR', position: 'insideBottom', offset: -8, fontSize: 12 }}
        />
        <YAxis tick={{ fontSize: 12 }} width={36} label={{ value: 'сценарии', angle: -90, position: 'insideLeft', fontSize: 12 }} />
        <Tooltip
          formatter={(v) => [`${v} сценария`, 'брой']}
          labelFormatter={(x) => `IRR ≈ ${pct(Number(x))}`}
        />
        <ReferenceLine
          x={data.reduce((best, b) => (Math.abs(b.irr - hurdle) < Math.abs(best - hurdle) ? b.irr : best), data[0]?.irr ?? hurdle)}
          stroke="#c0392b"
          strokeDasharray="4 2"
          label={{ value: `праг ${pct(hurdle)}`, fontSize: 11, fill: '#c0392b', position: 'top' }}
        />
        <Bar dataKey="count" radius={[2, 2, 0, 0]}>
          {data.map((b, i) => (
            <Cell key={i} fill={b.irr >= hurdle ? '#c55a11' : '#9aa7b6'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
