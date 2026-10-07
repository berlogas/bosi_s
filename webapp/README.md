# webapp — интерфейс boasi_s на React (TypeScript)

Новый SPA-интерфейс, заменяющий Streamlit (`frontend/`). План перехода —
`docs/REACT_MIGRATION_PLAN.md`. Бэкенд не меняется: тот же шина `/api/*`.

## Структура

```
src/
  api/          # fetch-клиент (refresh-очередь, ApiError) + schema.ts (codegen)
  app/          # общие провайдеры (Mantine, React Query, роутер)
  features/     # auth/ layout/ dashboard/ ... — по фичам
  routes.tsx    # маршруты; страницы сидят под AppLayout
  test/         # Vitest setup (jsdom-полифилы)
openapi/        # снимок спецификации бэкенда (генерируется, не править руками)
```

## Команды

```bash
npm ci            # установка
npm run dev       # dev-сервер (проксирует /api → http://localhost:8000)
npm run lint      # ESLint
npm run typecheck # tsc --strict (strict + noUncheckedIndexedAccess)
npm test          # Vitest (RTL-тесты, jsdom)
npm run build     # production-сборка в dist/
npm run format    # Prettier

npm run codegen       # перегенерировать src/api/schema.ts из openapi/spec.json
npm run codegen:check # CI: убедиться, что типы не устарели
```

Обновление снимка спецификации после правок бэкенда:

```bash
curl -s http://localhost:8000/api/openapi.json > openapi/spec.json
npm run codegen
```

## Как это работает

- **Dev**: Vite отдаёт код и проксирует `/api` на бэкенд — CORS не нужен.
  **Prod**: FastAPI монтирует `webapp/dist` (по плану, фаза 5) — один порт.
- **Токены**: access в памяти, refresh в `localStorage` — сессия переживает
  F5. При 401 — один общий refresh (параллельные запросы ждут очередь),
  повтор, при провале — выход на экран входа.
- **Ошибки**: любой сбой API → `ApiError` с русским текстом, `meta`
  (лимиты) доезжает до UI.

## Тесты

- `src/api/client.test.ts` — refresh-очередь, ротация токенов, разбор
  ошибок (паритет `_explain` из Streamlit-клиента), сетевые сбои;
- `src/features/auth/loginPage.test.tsx` — приёмка Фазы 0: вход →
  пустой дашборд, ошибки формы.

CI: `.github/workflows/webapp.yml` (codegen:check → lint → format →
typecheck → test → build).
