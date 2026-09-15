import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { hostPorts } from './ports.ts'

const ports = hostPorts()

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  preview: { host: '127.0.0.1', port: ports.vite, strictPort: true },
  server: {
    host: '127.0.0.1',
    port: ports.vite,
    strictPort: true,
    proxy: { '/api': `http://127.0.0.1:${ports.ui}` },
  },
})
