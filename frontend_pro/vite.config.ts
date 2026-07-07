import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  base: '/pro/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: '../static_pro',
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        configure: (proxy: any) => {
          proxy.on('proxyRes', (proxyRes: any) => {
            proxyRes.headers['X-Accel-Buffering'] = 'no'
            proxyRes.headers['Cache-Control'] = 'no-cache'
          })
        },
      },
    },
  },
})

