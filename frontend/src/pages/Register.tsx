import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { ApiError } from '../api'

export default function Register() {
  const { user, register } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [company, setCompany] = useState('')
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!consent) {
      setError('Съгласието с обработката на данни е задължително')
      return
    }
    setBusy(true)
    try {
      await register({
        email,
        password,
        full_name: fullName || undefined,
        company: company || undefined,
        gdpr_consent: consent,
      })
      navigate('/')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setError('Този имейл вече е регистриран')
      else if (err instanceof ApiError && err.status === 422) setError('Паролата трябва да е поне 8 символа, имейлът — валиден')
      else setError('Възникна грешка при регистрацията')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="center-screen">
      <form className="card auth-card" onSubmit={onSubmit}>
        <h1>Регистрация</h1>
        {error && <div className="error">{error}</div>}
        <label>Имейл *</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        <label>Парола * (мин. 8 символа)</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        <label>Име и фамилия</label>
        <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
        <label>Фирма</label>
        <input value={company} onChange={(e) => setCompany(e.target.value)} />
        <div className="checkbox">
          <input id="gdpr" type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <label htmlFor="gdpr" style={{ margin: 0 }}>
            Съгласявам се с обработката на личните ми данни (GDPR). *
          </label>
        </div>
        <button type="submit" disabled={busy} style={{ width: '100%', marginTop: 18 }}>
          {busy ? 'Създаване…' : 'Създай профил'}
        </button>
        <p className="muted" style={{ marginTop: 16, textAlign: 'center' }}>
          Вече имаш профил? <Link to="/login">Вход</Link>
        </p>
      </form>
    </div>
  )
}
