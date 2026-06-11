import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

export default function TopBar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const onLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="topbar">
      <Link to="/" className="brand">Buildflow<span> AI</span></Link>
      <div className="right">
        <span className="muted" style={{ color: '#cdd7e3' }}>{user?.email}</span>
        <button className="link" style={{ color: '#fff' }} onClick={onLogout}>Изход</button>
      </div>
    </div>
  )
}
