import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  api, ApiError,
  type Project as ProjectT, type SectionResponse,
  type Summary, type RouteStep, type FeeItem, type Economics,
  type ScheduleData, type NodePatchResult, type RiskResult,
} from '../api'
import Gantt from '../components/Gantt'
import CashflowChart from '../components/CashflowChart'
import RiskHistogram from '../components/RiskHistogram'

const TIER_RANK: Record<string, number> = { free: 0, standard: 1, pro: 2, dd: 3 }

const SECTIONS = [
  { key: 'summary', label: 'Резюме', tier: 'free' },
  { key: 'route', label: 'Маршрут', tier: 'standard' },
  { key: 'fees', label: 'Такси', tier: 'standard' },
  { key: 'schedule', label: 'График', tier: 'pro' },
  { key: 'economics', label: 'Икономика', tier: 'pro' },
  { key: 'journal', label: 'Журнал', tier: 'pro' },
  { key: 'risk', label: 'Риск', tier: 'dd' },
  { key: 'export', label: 'Експорт', tier: 'dd' },
]

const money = (n: number) => n.toLocaleString('bg-BG', { maximumFractionDigits: 0 }) + ' лв'

export default function Project() {
  const { id } = useParams()
  const [project, setProject] = useState<ProjectT | null>(null)
  const [active, setActive] = useState('summary')
  const [section, setSection] = useState<SectionResponse | null>(null)
  const [state, setState] = useState<'ok' | 'loading' | 'locked' | 'soon' | 'norecalc' | 'error'>('loading')
  const [recalcing, setRecalcing] = useState(false)

  useEffect(() => {
    api.get<ProjectT>(`/projects/${id}`).then(setProject).catch(() => setState('error'))
  }, [id])

  const tierRank = project ? TIER_RANK[project.tier] : -1

  const loadSection = useCallback(async (key: string) => {
    const meta = SECTIONS.find((s) => s.key === key)!
    if (tierRank < TIER_RANK[meta.tier]) {
      setState('locked')
      setSection(null)
      return
    }
    setState('loading')
    try {
      setSection(await api.get<SectionResponse>(`/projects/${id}/sections/${key}`))
      setState('ok')
    } catch (err) {
      if (err instanceof ApiError && err.status === 501) setState('soon')
      else if (err instanceof ApiError && err.status === 409) setState('norecalc')
      else setState('error')
    }
  }, [id, tierRank])

  useEffect(() => {
    if (project) loadSection(active)
  }, [project, active, loadSection])

  const recalc = async () => {
    setRecalcing(true)
    try {
      await api.post(`/projects/${id}/recalc`)
      await loadSection(active)
    } finally {
      setRecalcing(false)
    }
  }

  if (state === 'error' && !project) return <div className="error">Проектът не е намерен.</div>
  if (!project) return <p className="muted">Зареждане…</p>

  const activeMeta = SECTIONS.find((s) => s.key === active)!

  return (
    <>
      <div className="spread" style={{ marginBottom: 18 }}>
        <div>
          <h1 style={{ marginBottom: 4 }}>{project.name}</h1>
          <span className={`badge ${project.tier}`}>{project.tier}</span>
          <span className="muted" style={{ marginLeft: 10 }}>{project.project_type_id}</span>
        </div>
        <button className="secondary" onClick={recalc} disabled={recalcing}>
          {recalcing ? 'Преизчисляване…' : 'Преизчисли'}
        </button>
      </div>

      <div className="project-layout">
        <nav className="section-nav">
          {SECTIONS.map((s) => {
            const locked = tierRank < TIER_RANK[s.tier]
            return (
              <button
                key={s.key}
                className={`${active === s.key ? 'active' : ''} ${locked ? 'locked' : ''}`}
                onClick={() => setActive(s.key)}
              >
                {s.label}
                {locked && <span className="lock">🔒</span>}
              </button>
            )
          })}
        </nav>

        <div className="card">
          <h2>{activeMeta.label}</h2>
          {state === 'loading' && <p className="muted">Зареждане…</p>}
          {state === 'locked' && <LockedPanel required={activeMeta.tier} />}
          {state === 'soon' && <p className="muted">Тази секция предстои (фаза 3).</p>}
          {state === 'norecalc' && (
            <p className="muted">Още няма изчисление. <button className="link" onClick={recalc}>Преизчисли сега</button></p>
          )}
          {state === 'error' && <div className="error">Неуспешно зареждане на секцията.</div>}
          {state === 'ok' && section && (
            active === 'schedule' ? (
              <ScheduleSection
                projectId={id!}
                data={section.data as { schedule: ScheduleData }}
                onResult={(r) =>
                  setSection((prev) =>
                    prev ? { ...prev, data: { schedule: r.result.schedule, version_no: r.version_no } } : prev,
                  )
                }
              />
            ) : (
              <SectionBody name={active} data={section.data as Record<string, unknown>} />
            )
          )}
        </div>
      </div>
    </>
  )
}

const NODE_STATUS_LABELS: Record<string, string> = {
  pending: 'Предстои',
  active: 'В ход',
  done: 'Готова',
  delayed: 'Забавена',
}

function ScheduleSection({
  projectId,
  data,
  onResult,
}: {
  projectId: string
  data: { schedule: ScheduleData }
  onResult: (r: NodePatchResult) => void
}) {
  const sch = data.schedule
  const [sel, setSel] = useState<string | null>(null)
  const [dur, setDur] = useState('')
  const [status, setStatus] = useState('pending')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [banner, setBanner] = useState('')

  const pick = (pid: string) => {
    const n = sch.nodes[pid]
    setSel(pid)
    setDur(String(n.duration))
    setStatus(n.status ?? 'pending')
    setReason('')
    setErr('')
  }

  const save = async () => {
    if (!sel) return
    const n = sch.nodes[sel]
    const body: Record<string, unknown> = {}
    if (Number(dur) !== n.duration) body.planned_duration_days = Number(dur)
    if (status !== (n.status ?? 'pending')) body.status = status
    if (!('planned_duration_days' in body) && !('status' in body)) {
      setSel(null)
      return
    }
    if (body.status === 'delayed' && !reason.trim()) {
      setErr('Причината е задължителна при забавяне')
      return
    }
    if (reason.trim()) body.reason = reason.trim()
    setBusy(true)
    setErr('')
    try {
      const r = await api.patch<NodePatchResult>(`/projects/${projectId}/nodes/${sel}`, body)
      const d = r.delta_days ?? 0
      const irr = r.delta_irr_pp ?? 0
      setBanner(
        `Промяната измести срока с ${d >= 0 ? '+' : ''}${d} дни и IRR с ${irr >= 0 ? '+' : ''}${irr} п.п. (версия ${r.version_no})`,
      )
      onResult(r)
      setSel(null)
    } catch (e) {
      setErr(e instanceof ApiError && typeof e.detail === 'string' ? e.detail : 'Грешка при запис')
    } finally {
      setBusy(false)
    }
  }

  const selNode = sel ? sch.nodes[sel] : null

  return (
    <>
      <p>
        Общ срок: <strong>{sch.total_days}</strong> дни · <span className="tag-critical">червено = критичен път</span>
        <span className="muted"> · клик върху ред за редакция</span>
      </p>
      {banner && <div className="banner">{banner}</div>}
      <Gantt nodes={sch.nodes} totalDays={sch.total_days} selected={sel} onSelect={pick} />

      {sel && selNode && (
        <div className="card" style={{ marginTop: 16, background: 'var(--bg)' }}>
          <h2 style={{ marginBottom: 4 }}>{selNode.name ?? sel}</h2>
          <p className="muted" style={{ margin: 0 }}>ден {selNode.start}–{selNode.end}{selNode.critical ? ' · критичен път' : ''}</p>
          {err && <div className="error">{err}</div>}
          <div className="grid2">
            <div>
              <label>Продължителност (дни)</label>
              <input type="number" min={0} value={dur} onChange={(e) => setDur(e.target.value)} />
            </div>
            <div>
              <label>Статус</label>
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                {Object.entries(NODE_STATUS_LABELS).map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            </div>
          </div>
          <label>Причина {status === 'delayed' ? '(задължителна при забавяне)' : '(по избор)'}</label>
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="напр. забавена доставка" />
          <div className="row" style={{ marginTop: 14 }}>
            <button onClick={save} disabled={busy}>{busy ? 'Запазване…' : 'Запази и преизчисли'}</button>
            <button className="secondary" onClick={() => setSel(null)} disabled={busy}>Отказ</button>
          </div>
        </div>
      )}
    </>
  )
}

function LockedPanel({ required }: { required: string }) {
  return (
    <div className="locked-panel">
      <div className="big-lock">🔒</div>
      <p>Тази секция е достъпна от ниво <strong>{required}</strong> нагоре.</p>
      <button className="amber" disabled title="Плащанията предстоят">Надгради (скоро)</button>
    </div>
  )
}

function SectionBody({ name, data }: { name: string; data: Record<string, unknown> }) {
  if (name === 'summary') {
    const s = data.summary as Summary
    return (
      <div className="stat-grid">
        <div className="stat"><div className="v">{s.procedure_count}</div><div className="k">процедури</div></div>
        <div className="stat"><div className="v">{s.total_days}</div><div className="k">дни (критичен път)</div></div>
        <div className="stat"><div className="v">{money(s.total_fees)}</div><div className="k">общо такси</div></div>
      </div>
    )
  }

  if (name === 'route') {
    const steps = data.route as RouteStep[]
    return (
      <table>
        <thead><tr><th>Процедура</th><th>Институция</th><th>Основание</th><th className="num">Дни</th></tr></thead>
        <tbody>
          {steps.map((r) => (
            <tr key={r.procedure_id}>
              <td>{r.name} {r.is_critical && <span className="tag-critical">• критична</span>}</td>
              <td className="muted">{r.institution}</td>
              <td className="muted">{r.act ?? '—'}</td>
              <td className="num">{r.duration_days}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }

  if (name === 'fees') {
    const fees = data.fees as { items: FeeItem[]; total: number }
    return (
      <table>
        <thead><tr><th>Такса</th><th>Основание</th><th className="num">Сума</th></tr></thead>
        <tbody>
          {fees.items.map((f) => (
            <tr key={f.fee_id}>
              <td>{f.description}</td>
              <td className="muted">{f.citation ? `${f.citation.title} ${f.citation.article ?? ''}` : '—'}</td>
              <td className="num">{money(f.amount)}</td>
            </tr>
          ))}
          <tr><td colSpan={2}><strong>Общо</strong></td><td className="num"><strong>{money(fees.total)}</strong></td></tr>
        </tbody>
      </table>
    )
  }

  // 'schedule' is rendered by ScheduleSection (it needs project id + editing state)

  if (name === 'economics') {
    const e = data.economics as Economics
    const pct = (x: number) => (x * 100).toFixed(1) + '%'
    return (
      <>
        <div className="stat-grid">
          <div className="stat"><div className="v">{money(e.capex)}</div><div className="k">CAPEX</div></div>
          <div className="stat"><div className="v">{pct(e.irr)}</div><div className="k">IRR</div></div>
          <div className="stat"><div className="v">{money(e.npv)}</div><div className="k">NPV</div></div>
          <div className="stat"><div className="v">{e.lcoe.toFixed(1)}</div><div className="k">LCOE (лв/MWh)</div></div>
          <div className="stat"><div className="v">{e.payback_years.toFixed(1)}</div><div className="k">изплащане (год)</div></div>
          <div className="stat"><div className="v" style={{ textTransform: 'capitalize' }}>{e.verdict}</div><div className="k">присъда</div></div>
        </div>
        {e.cashflow && (
          <div style={{ marginTop: 20 }}>
            <h2>Паричен поток (20 г.)</h2>
            <CashflowChart data={e.cashflow} />
          </div>
        )}
      </>
    )
  }

  if (name === 'risk') {
    const r = data.risk as RiskResult
    const pct = (x: number) => (x * 100).toFixed(1) + '%'
    return (
      <>
        <div className={`banner ${r.resilient ? '' : 'risk-warn'}`}>
          {r.resilient
            ? `Устойчив проект: дори песимистичният сценарий (P5) минава прага от ${pct(r.hurdle)}.`
            : `Внимание: песимистичният сценарий (P5 = ${pct(r.irr_p5)}) пада под прага от ${pct(r.hurdle)}.`}
        </div>
        <div className="stat-grid">
          <div className="stat"><div className="v">{pct(r.p_pass)}</div><div className="k">минава прага ({r.n} сценария)</div></div>
          <div className="stat"><div className="v">{pct(r.p_npv_positive)}</div><div className="k">NPV &gt; 0</div></div>
          <div className="stat"><div className="v">{pct(r.irr_p50)}</div><div className="k">медиана IRR (P50)</div></div>
          <div className="stat"><div className="v">{pct(r.irr_p5)}</div><div className="k">песимистичен (P5)</div></div>
          <div className="stat"><div className="v">{pct(r.irr_p95)}</div><div className="k">оптимистичен (P95)</div></div>
          <div className="stat"><div className="v" style={{ color: r.resilient ? 'var(--green)' : 'var(--amber)' }}>{r.resilient ? 'устойчив' : 'граничен'}</div><div className="k">оценка на риска</div></div>
        </div>
        <div style={{ marginTop: 20 }}>
          <h2>Разпределение на IRR (Monte Carlo)</h2>
          <RiskHistogram data={r.histogram} hurdle={r.hurdle} />
        </div>
      </>
    )
  }

  if (name === 'journal') {
    const events = data.journal as { event_type: string; created_at: string; payload: Record<string, unknown> }[]
    return (
      <table>
        <thead><tr><th>Събитие</th><th>Кога</th></tr></thead>
        <tbody>
          {events.map((ev, i) => (
            <tr key={i}>
              <td>{ev.event_type}</td>
              <td className="muted">{new Date(ev.created_at).toLocaleString('bg-BG')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }

  return <pre>{JSON.stringify(data, null, 2)}</pre>
}
