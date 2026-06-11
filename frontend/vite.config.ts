import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend runs on :8000. We proxy the API paths so the browser talks to
// one origin (the Vite dev server) — no CORS, and the httpOnly auth cookie is
// sent like same-origin. In production the SPA and API sit behind one nginx.
const apiPaths = ['/auth', '/projects', '/catalog', '/admin', '/health']

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      apiPaths.map((p) => [p, { target: 'http://127.0.0.1:8000', changeOrigin: true }]),
    ),
  },
})
