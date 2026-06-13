import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  api, ApiError,
  type Project as ProjectT, type SectionResponse,
  type Summary, type RouteStep, type FeeItem, type Economics,
  type ScheduleData, type NodePatchResult, type RiskResult,
  type ValidationRequest,
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
  const [state, setState] = useState<'ok' | 'loading' | 'locked' | 'soon' | 'norecalc' | 'error' | 'export'>('loading')
  const [recalcing, setRecalcing] = useState(false)
  const [subscribed, setSubscribed] = useState<boolean | null>(null)

  useEffect(() => {
    api.get<ProjectT>(`/projects/${id}`).then(setProject).catch(() => setState('error'))
    api.get<{ status: string } | null>(`/projects/${id}/subscription`)
      .then((s) => setSubscribed(!!s)).catch(() => setSubscribed(false))
  }, [id])

  const toggleSubscription = async () => {
    if (subscribed) {
      await api.del(`/projects/${id}/subscription`)
      setSubscribed(false)
    } else {
      await api.post(`/projects/${id}/subscription`)
      setSubscribed(true)
    }
  }

  const tierRank = project ? TIER_RANK[project.tier] : -1

  const loadSection = useCallback(async (key: string) => {
    const meta = SECTIONS.find((s) => s.key === key)!
    if (tierRank < TIER_RANK[meta.tier]) {
      setState('locked')
      setSection(null)
      return
    }
    // Export isn't section data — it's a file download; render the panel directly.
    if (key === 'export') {
      setSection(null)
      setState('export')
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
        <div className="row">
          {project.tier !== 'free' && subscribed !== null && (
            <button
              className={subscribed ? 'amber' : 'secondary'}
              onClick={toggleSubscription}
              title="Мониторинг на актове и тарифи с авто-преизчисление"
            >
              {subscribed ? '🔔 Актуалност: вкл.' : '🔕 Актуалност: изкл.'}
            </button>
          )}
          <button className="secondary" onClick={recalc} disabled={recalcing}>
            {recalcing ? 'Преизчисляване…' : 'Преизчисли'}
          </button>
        </div>
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
          {state === 'export' && <ExportSection projectId={id!} />}
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
          <p className="muted" style={{ margin: 0 }}>
            {selNode.start_date ? `${selNode.start_date} – ${selNode.end_date}` : `ден ${selNode.start}–${selNode.end}`}
            {selNode.critical ? ' · критичен път' : ''}
          </p>
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

const VALIDATION_LABELS: Record<ValidationRequest['status'], string> = {
  requested: 'Заявена — чака преглед',
  in_review: 'В преглед от експерт',
  approved: 'Заверена ✔',
  rejected: 'Отхвърлена',
}

function ExportSection({ projectId }: { projectId: string }) {
  const today = new Date().toLocaleDateString('bg-BG')
  const [validation, setValidation] = useState<ValidationRequest | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.get<ValidationRequest | null>(`/projects/${projectId}/validation`).then(setValidation).catch(() => {})
  }, [projectId])

  const requestValidation = async () => {
    setBusy(true)
    setErr('')
    try {
      setValidation(await api.post<ValidationRequest>(`/projects/${projectId}/validation`, {}))
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 409 ? 'Вече има подадена заявка.' : 'Грешка при заявката')
    } finally {
      setBusy(false)
    }
  }

  const pending = validation && (validation.status === 'requested' || validation.status === 'in_review')

  return (
    <div style={{ padding: '12px' }}>
      <div style={{ textAlign: 'center' }}>
        <p>Excel пакет с всички секции (Резюме, Маршрут, Такси, График, Икономика).</p>
        <div className="row" style={{ justifyContent: 'center' }}>
          <a href={`/projects/${projectId}/export/xlsx`} download>
            <button className="amber" type="button">⬇ Изтегли Excel</button>
          </a>
          <a href={`/projects/${projectId}/export/pdf`} download>
            <button className="secondary" type="button">⬇ Изтегли PDF</button>
          </a>
        </div>
        <p className="muted" style={{ marginTop: 16, fontSize: 13 }}>
          Докладът се генерира от последното изчисление и носи печат „изчислено по актове в сила към {today}“.
        </p>
      </div>

      <div className="card" style={{ marginTop: 16, background: 'var(--bg)' }}>
        <h2>Експертна валидация</h2>
        {err && <div className="error">{err}</div>}
        {!validation && (
          <>
            <p className="muted">Заяви преглед от експерт, който при одобрение прикача заверен PDF.</p>
            <button onClick={requestValidation} disabled={busy}>
              {busy ? 'Изпращане…' : 'Заяви експертна валидация'}
            </button>
          </>
        )}
        {validation && (
          <p>
            Статус: <strong>{VALIDATION_LABELS[validation.status]}</strong>
            {validation.review_note && <span className="muted"> — {validation.review_note}</span>}
            {validation.certified_pdf_url && (
              <> · <a href={validation.certified_pdf_url} target="_blank" rel="noreferrer">заверен PDF</a></>
            )}
            {pending && <span className="muted"> · можеш да изтеглиш Excel-а междувременно</span>}
          </p>
        )}
      </div>
    </div>
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
        <thead><tr><th>Процедура</th><th>Институция</th><th>Документи</th><th>Основание</th><th className="num">Дни</th></tr></thead>
        <tbody>
          {steps.map((r) => (
            <tr key={r.procedure_id}>
              <td>{r.name} {r.is_critical && <span className="tag-critical">• критична</span>}</td>
              <td className="muted">{r.institution}</td>
              <td className="muted" style={{ fontSize: 12.5 }}>
                {r.input_documents.length > 0 && <span title="входни документи">вх: {r.input_documents.join(', ')}</span>}
                {r.input_documents.length > 0 && r.output_document && <br />}
                {r.output_document && <span title="изходен документ">→ {r.output_document}</span>}
                {r.input_documents.length === 0 && !r.output_document && '—'}
              </td>
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
