import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期 /api 反代到本机 FastAPI；生产由 Nginx 反代
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
