# webapp — интерфейс boasi_s на React (TypeScript)

Новый SPA-интерфейс, заменяющий Streamlit (`frontend/`). План перехода —
`docs/REACT_MIGRATION_PLAN.md`. Бэкенд не меняется: тот же шина `/api/*`.

## Структура

```
src/
  api/          # fetch-клиент (refresh-очередь, ApiError) + schema.ts (codegen)
  app/          # общие провайдеры (Mantine, React Query, роутер)
  components/   # переиспользуемые: TaskPanel, AnswerView, MarkdownText, …
  features/     # auth/ layout/ dashboard/ chat/ sessions/ — по фичам
  routes.tsx    # маршруты; страницы сидят под AppLayout
  test/         # Vitest setup (jsdom-полифилы) и общие фикстуры
e2e/            # Playwright-приёмка (моки сети, бэкенд не нужен)
openapi/        # снимок спецификации бэкенда (генерируется, не править руками)
```

## Команды

```bash
npm ci            # установка
npm run dev       # dev-сервер (проксирует /api → http://localhost:8000)
npm run lint      # ESLint
npm run typecheck # tsc --strict (strict + noUncheckedIndexedAccess)
npm test          # Vitest (RTL-тесты, jsdom)
npm run test:e2e   # Playwright (нужен `npx playwright install chromium`)
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
- `src/features/auth/loginPage.test.tsx` — вход: ошибки формы, успех →
  пустой дашборд;
- `src/features/dashboard/dashboard.test.tsx` — приёмка Фазы 1:
  список/группы сессий с TTL, создание, архив в два шага с модалкой,
  активные задачи (поллинг, отмена), быстрый чат (ответ, источники,
  ошибки);
- `src/features/chat/chat.test.tsx` — чат сессии (Фазы 2): история
  пузырями, удаление пары, фоновая задача (панель → done/error), F5-
  восстановление, очистка в два шага, read-only архива;
- `src/components/answerView.test.tsx` — ответ: клик по цитате `[n]`
  подсвечивает источник, санитизация markdown, References, предупреждения
  grounding;
- `e2e/phase1.spec.ts` — приёмка в настоящем браузере: вход → создать
  сессию → заархивировать с подтверждением. API мокается на уровне
  сети (`page.route`), поэтому e2e не требует бэкенда — работает в CI.
- `e2e/phase2.spec.ts` — чат: долгий вопрос → панель этапов → отмена,
  предупреждения grounding, References + клик по цитате, восстановление
  поллинга после F5.

Чтобы гонять e2e против живого API — уберите моки из спеки: Vite
проксирует `/api` на `localhost:8000`.

CI: `.github/workflows/webapp.yml` (codegen:check → lint → format →
typecheck → test → e2e → build).
