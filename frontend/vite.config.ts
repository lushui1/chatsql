import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5180,
    proxy: {
      '/v1': 'http://127.0.0.1:8020',
      '/healthz': 'http://127.0.0.1:8020',
      '/readyz': 'http://127.0.0.1:8020',
    },
  },
})
