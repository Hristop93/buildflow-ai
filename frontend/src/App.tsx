import { Navigate, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './auth'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Wizard from './pages/Wizard'
import Project from './pages/Project'
import TopBar from './components/TopBar'

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="center-screen muted">Зареждане…</div>
  if (!user) return <Navigate to="/login" replace />
  return (
    <>
      <TopBar />
      <div className="container">{children}</div>
    </>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/" element={<Protected><Dashboard /></Protected>} />
      <Route path="/new" element={<Protected><Wizard /></Protected>} />
      <Route path="/projects/:id" element={<Protected><Project /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
