import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Project } from '../api'

export default function Dashboard() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<Project[]>('/projects').then(setProjects).catch(() => setError('Неуспешно зареждане на проектите'))
  }, [])

  return (
    <>
      <div className="spread" style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0 }}>Моите проекти</h1>
        <button className="amber" onClick={() => navigate('/new')}>+ Нов проект</button>
      </div>

      {error && <div className="error">{error}</div>}

      {projects === null && !error && <p className="muted">Зареждане…</p>}

      {projects && projects.length === 0 && (
        <div className="card" style={{ textAlign: 'center', padding: 40 }}>
          <p className="muted">Още нямаш проекти.</p>
          <button className="amber" onClick={() => navigate('/new')}>Създай първия си проект</button>
        </div>
      )}

      {projects && projects.length > 0 && (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr><th>Име</th><th>Тип</th><th>Ниво</th><th>Статус</th></tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/projects/${p.id}`)}>
                  <td><Link to={`/projects/${p.id}`}>{p.name}</Link></td>
                  <td className="muted">{p.project_type_id}</td>
                  <td><span className={`badge ${p.tier}`}>{p.tier}</span></td>
                  <td className="muted">{p.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
