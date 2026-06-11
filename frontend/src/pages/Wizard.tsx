import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type Project } from '../api'

const STEPS = ['Тип и ниво', 'Локация', 'Технически', 'Финансови']

// Inputs the user does not set in this MVP keep representative defaults
// (matching the verified PV example) so recalc has everything it needs.
const HIDDEN_DEFAULTS = {
  specific_capex_per_kw: 1300,
  degradation: 0.005,
  years: 20,
  tax_rate: 0.1,
}

export default function Wizard() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const [name, setName] = useState('')
  const [tier, setTier] = useState('pro')
  const [landStatus, setLandStatus] = useState('agricultural')
  const [voltage, setVoltage] = useState('medium')
  const [protectedZone, setProtectedZone] = useState(false)
  const [powerMw, setPowerMw] = useState('5')
  const [rzp, setRzp] = useState('500')
  const [investValue, setInvestValue] = useState('10000000')
  const [ppa, setPpa] = useState('160')
  const [yield_, setYield] = useState('1350')
  const [opex, setOpex] = useState('25')
  const [wacc, setWacc] = useState('8')
  const [hurdle, setHurdle] = useState('9')

  const canNext = step === 0 ? name.trim().length > 0 : true

  const submit = async () => {
    setError('')
    setBusy(true)
    try {
      const params = {
        land_status: landStatus,
        voltage,
        protected_zone: protectedZone,
        power_mw: Number(powerMw),
        rzp_sqm: Number(rzp),
        invest_value: Number(investValue),
        ppa_price: Number(ppa),
        yield_kwh_kwp: Number(yield_),
        opex_per_kw: Number(opex),
        wacc: Number(wacc) / 100,
        hurdle_rate: Number(hurdle) / 100,
        ...HIDDEN_DEFAULTS,
      }
      const project = await api.post<Project>('/projects', {
        name: name.trim(),
        project_type_id: 'pv_ground',
        tier,
        params,
      })
      await api.post(`/projects/${project.id}/recalc`)
      navigate(`/projects/${project.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? `Грешка: ${String(err.detail)}` : 'Възникна грешка')
      setBusy(false)
    }
  }

  return (
    <>
      <h1>Нов проект</h1>
      <div className="wizard-steps">
        {STEPS.map((label, i) => (
          <div key={label} className={`step ${i === step ? 'active' : i < step ? 'done' : ''}`}>
            {i + 1}. {label}
          </div>
        ))}
      </div>

      <div className="card">
        {error && <div className="error">{error}</div>}

        {step === 0 && (
          <>
            <label>Име на проекта *</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="напр. ФЕЦ Варна 5 MW" autoFocus />
            <label>Тип проект</label>
            <select value="pv_ground" disabled>
              <option value="pv_ground">Наземна фотоволтаична централа</option>
            </select>
            <p className="muted" style={{ fontSize: 13 }}>Други типове — очаквайте скоро.</p>
            <label>Ниво (засега се избира ръчно — плащанията предстоят)</label>
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="free">Free — само Резюме</option>
              <option value="standard">Standard — + Маршрут и Такси</option>
              <option value="pro">Pro — + График, Икономика, Журнал</option>
              <option value="dd">Due-diligence — всичко</option>
            </select>
          </>
        )}

        {step === 1 && (
          <>
            <label>Статут на земята</label>
            <select value={landStatus} onChange={(e) => setLandStatus(e.target.value)}>
              <option value="agricultural">Земеделска</option>
              <option value="urban">Урбанизирана</option>
              <option value="industrial">Индустриална</option>
            </select>
            <label>Напрежение на присъединяване</label>
            <select value={voltage} onChange={(e) => setVoltage(e.target.value)}>
              <option value="medium">Средно</option>
              <option value="high">Високо</option>
            </select>
            <div className="checkbox">
              <input id="pz" type="checkbox" checked={protectedZone} onChange={(e) => setProtectedZone(e.target.checked)} />
              <label htmlFor="pz" style={{ margin: 0 }}>Попада в защитена зона (Натура 2000)</label>
            </div>
          </>
        )}

        {step === 2 && (
          <div className="grid2">
            <div>
              <label>Мощност (MW)</label>
              <input type="number" value={powerMw} onChange={(e) => setPowerMw(e.target.value)} />
            </div>
            <div>
              <label>РЗП на сградите (кв.м)</label>
              <input type="number" value={rzp} onChange={(e) => setRzp(e.target.value)} />
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="grid2">
            <div>
              <label>Инвестиционна стойност (лв)</label>
              <input type="number" value={investValue} onChange={(e) => setInvestValue(e.target.value)} />
            </div>
            <div>
              <label>Цена PPA (лв/MWh)</label>
              <input type="number" value={ppa} onChange={(e) => setPpa(e.target.value)} />
            </div>
            <div>
              <label>Добив (kWh/kWp)</label>
              <input type="number" value={yield_} onChange={(e) => setYield(e.target.value)} />
            </div>
            <div>
              <label>OPEX (лв/kW/год)</label>
              <input type="number" value={opex} onChange={(e) => setOpex(e.target.value)} />
            </div>
            <div>
              <label>WACC (%)</label>
              <input type="number" value={wacc} onChange={(e) => setWacc(e.target.value)} />
            </div>
            <div>
              <label>Изискуема норма (%)</label>
              <input type="number" value={hurdle} onChange={(e) => setHurdle(e.target.value)} />
            </div>
          </div>
        )}

        <div className="spread" style={{ marginTop: 24 }}>
          <button className="secondary" onClick={() => (step === 0 ? navigate('/') : setStep(step - 1))} disabled={busy}>
            {step === 0 ? 'Отказ' : 'Назад'}
          </button>
          {step < STEPS.length - 1 ? (
            <button onClick={() => setStep(step + 1)} disabled={!canNext}>Напред</button>
          ) : (
            <button className="amber" onClick={submit} disabled={busy}>
              {busy ? 'Изчисляване…' : 'Генерирай'}
            </button>
          )}
        </div>
      </div>
    </>
  )
}
