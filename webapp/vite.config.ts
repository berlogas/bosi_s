import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { visualizer } from 'rollup-plugin-visualizer'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Bundle budget визуализатор (Волна 6, п.3): запускать через
    // `vite build --mode analyze` для отчёта размера чанков
    process.env.ANALYZE === 'true' && visualizer({
      open: false,
      filename: 'stats.html',
      gzipSize: true,
      brotliSize: true,
    }),
  ],
  build: {
    // Предупреждение, если чанк больше 500 КБ — нужно делать код-сплиттинг
    chunkSizeWarningLimit: 500,
  },
  server: {
    proxy: {
      // Dev: Vite отдаёт и код, и API с одного origin — CORS не нужен.
      // В Docker цель задаётся через VITE_API_TARGET (по умолчанию http://localhost:8000).
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        // Важно: проксировать Authorization заголовок на бэкенд
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            const auth = req.headers['authorization']
            if (auth) proxyReq.setHeader('Authorization', auth)
          })
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Даты форматируются в локальной зоне: фиксируем её, иначе ожидания
    // в тестах зависят от машины и CI (UTC).
    env: { TZ: 'Europe/Moscow' },
    globals: true,
    css: false,
    // Вкладки сессии грузятся лениво (React.lazy + code splitting): первый
    // импорт графа модулей в холодном кэше занимает дольше 5 с, и тест
    // падал по таймауту, не успев дождаться чанка.
    testTimeout: 30000,
    // e2e гоняет Playwright, а не Vitest (см. playwright.config.ts)
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
  },
})