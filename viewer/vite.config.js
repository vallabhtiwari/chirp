import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' keeps every asset path relative, so the same build works at
// http://127.0.0.1:8000/ (viewer.py) and at https://<user>.github.io/<repo>/ (Pages).
// In dev (npm run dev), /api is forwarded to viewer.py, which must be running.
export default defineConfig({
  base: './',
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
})
