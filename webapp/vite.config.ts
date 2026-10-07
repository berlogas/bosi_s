import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Dev: Vite отдаёт и код, и API с одного origin — CORS не нужен.
      // Prod: FastAPI монтирует webapp/dist, прокси не участвует.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
    // e2e гоняет Playwright, а не Vitest (см. playwright.config.ts)
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
  },
})
