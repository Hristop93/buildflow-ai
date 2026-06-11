import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, ApiError, type User } from './api'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (data: RegisterData) => Promise<void>
  logout: () => Promise<void>
}

export interface RegisterData {
  email: string
  password: string
  full_name?: string
  company?: string
  gdpr_consent: boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // Restore the session on first load (the cookie may already be valid).
  useEffect(() => {
    api
      .get<User>('/auth/me')
      .then(setUser)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e)
      })
      .finally(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string) => {
    setUser(await api.post<User>('/auth/login', { email, password }))
  }

  const register = async (data: RegisterData) => {
    setUser(await api.post<User>('/auth/register', data))
  }

  const logout = async () => {
    await api.post('/auth/logout')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
