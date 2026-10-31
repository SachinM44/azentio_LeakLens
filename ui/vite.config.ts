import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev the UI calls /api/* and Vite forwards it to the FastAPI server, so no CORS setup is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
