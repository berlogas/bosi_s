# ESLint / Vitest / CI-проблемы boasi_s

## 0. Общий статус

- Веб-приложение: `tsc -b --force` — успех.
- ESLint: 37 проблем (35 ошибок, 2 предупреждения).
- Vitest: 234 теста, 222 прошли, 5 провалов, 7 skipped.
- Backend (для справки): `ruff check app tests` — 97 ошибок/предупреждений.

## 1. Frontend: ESLint ошибки

### 1.1 `src/features/layout/NavSection.tsx`
- `useState` вызывается условно:
  - строка 28, если `hasChildren`, и строка 105.
- Это нарушает `react-hooks/rules-of-hooks`.
- Рекомендация: вынести `open`/`setOpen` на уровень компонента `NavSection` или всегда инициализировать его вне ветки.
- `disabled` содержит `any`:
  - `item.enabled` может быть функцией, но `enabled(null as any)` приводит к `any`.
- Рекомендация: явно типизировать `enabled`, не приводить к `any`.

### 1.2 `src/features/layout/appLayout.test.tsx`
- Файл не запускает `within`, хотя тесты предназначены для проверки вложенных элементов.
- Рекомендация: либо удалить, либо использовать `within` для проверок вложенности.
- `sessionStorage.clear()` вызывается без `afterEach`; фикстуры могут «катиться» от теста к тесту.

### 1.3 `src/features/layout/menuConfig.tsx`
- `IconSettings` импортируется, но не используется.
- Рекомендация: удалить неиспользуемый импорт.

### 1.4 `src/features/layout/LeftPanelUserMenu.tsx`
- `IconUserCircle` не используется.
- Рекомендация: удалить или заменить на нужный икон-компонент.

### 1.5 `src/features/layout/Breadcrumb.tsx`
- `activeProjectId` не используется.
- Рекомендация: удалить или добавить в логику.

### 1.6 `src/features/layout/appLayout.test.tsx`
- Файл содержит `within` не используется.
- `renderPath` внутри тестов не очищает `sessionStorage` при каждом вызове.
- Рекомендация: вынести `sessionStorage.clear()` в `beforeEach` или `afterEach`.

### 1.7 `src/features/layout/CommandPalette.tsx`
- `any` в типе параметра или возвращаемого значения.
- Рекомендация: определить тип запроса палитры или использовать `unknown` + проверку.

### 1.8 `src/features/layout/AsyncBoundary.a11y.test.tsx`
- `console` запрещён, но тест использует `console`.
- Рекомендация: заменить на `console.error`/`console.warn` или убрать тест.

### 1.9 `src/features/layout/EmptyState.tsx`
- `Button` и `defaultIcons` не используются.
- Рекомендация: удалить неиспользуемые переменные или декларации.

### 1.10 `src/features/chat/ChatTab.tsx`
- `sendError` не используется.
- `useEffect` имеет неполный набор зависимостей `streaming`.
- Рекомендация: либо добавить зависимость, либо переписать эффект без `streaming`.
- Рекомендация: удалить неиспользуемую переменную.

### 1.11 `src/features/chat/taskStorage.ts`
- `KEY` — строка, но `loadChatTask`/`saveChatTask`/`clearChatTask` не защищены от `JSON.parse` ошибок: защита есть, но тесты могут оставлять битые значения.
- Рекомендация: не изменять, но добавить тест с битым JSON.

### 1.12 `src/features/projects/GeneratePanel.tsx`
- `language` присваивается, но не используется.
- Рекомендация: удалить или использовать в UI/логике.

### 1.13 `src/features/projects/Toolbar.tsx`
- `no-useless-escape` на `` ` ``.
- Рекомендация: убрать экранирование.

### 1.14 `src/features/projects/UseProjectsReturn.ts`
- `UseProjectsReturn` не используется.
- Рекомендация: удалить или использовать в `useProjects`.

### 1.15 `src/features/projects/queries.ts`
- `any` в типе параметра или возвращаемого значения.
- Рекомендация: явно типизировать `useProjects` или `queries` функции.

### 1.16 `src/features/projects/ProjectDocumentsPanel.tsx`
- `useVirtualizer` возвращает функции, которые нельзя мемоизировать; ESLint предупреждает `incompatible-library`.
- Это предупреждение, а не критическая ошибка, но маска предупреждает о стейт-ловке UI.

### 1.17 `src/features/admin/admin.test.tsx`
- `sessionStorage.clear()` без `afterEach`.
- `localStorage.clear()` тоже.
- Рекомендация: добавить `afterEach`.

### 1.18 `src/features/admin/maintenance.test.tsx`
- 4 теста падают: ожидаемый элемент не найден.
- Проблема: `waitFor` или `findByText` не дождались элемента, или элемент не рендерится под тегом/текстом.
- Рекомендация:
  - Сменить метод поиска на `getBy` + `waitFor`, или `findBy` с правильным `timeout`.
  - Проверить имя кнопки/текста в UI.
  - Добавить `afterEach` для очистки уведомлений и `sessionStorage`.

### 1.19 `src/features/projects/projects.test.tsx`
- 1 тест падает: `waitFor` ожидает PATCH с телом `{ status: 'drafting' }`, но body другой.
- Рекомендация:
  - Проверить, что `PATCH` использует именно это поле.
  - Дождаться состояния сервера, а не сравнения body в момент первого вызова.
  - Можно замокать `PATCH`, но лучше проверить `JSON.parse` через `Object.fromEntries`.

## 2. Vitest: проваленные тесты

### 2.1 `src/features/admin/maintenance.test.tsx`
- `копия создаётся без ввода фразы — обычное подтверждение`
  - Ошибка: `expected [] to have a length of 1`.
  - Причина: элемент/уведомление не найден.
  - Скорее всего: UI не отрисовал элемент, тест использует неправильный `queryBy*`.
- `после создания список обновляется`
  - Ошибка: `expected [] to have a length of 1`.
- `показывает ошибку создания копии`
  - Ошибка: `Unable to find an element with the text: Не хватает места...`
  - Причина: текст разбит на элементы или отображается в портале.
- `список обновляется по-боевому: копия появляется сразу после создания`
  - Ошибка: `Unable to find an element with the text: boasi-20261008-133000.tar.gz`
  - Причина: имя файла разбито в DOM или элемент выдаётся асинхронно.

### 2.2 `src/features/projects/projects.test.tsx`
- `статус проекта сохраняется PATCH-ом при изменении`
  - Ошибка: `call.init.body` не содержит `{ status: 'drafting' }`.
  - Причина: PATCH отправляет другой ключ или payload формируется не по ожиданию.

### 2.3 Общий подход к отказу Vitest-тестов
- Не использовать `toHaveTextContent` для разбитого текста без функции-матча.
- Использовать `waitFor` или `findBy*` для асинхронных обновлений Mantine/React Query.
- Избегать `getBy*` без `defaultTimeout` когда элементы асинхронны.
- Не очищать хранилища только в `beforeEach` тестах, которые могут оставить стейт.

## 3. CI и окружение

### 3.1 Backend
- `pytest` не падает, но 420 предупреждений:
  - `RuntimeWarning: coroutine 'BaseLLMHTTPHandler.async_completion' was never awaited`
    - в `test_fusion_api.py`.
    - Это не падение, но указывает на пропавший `await` в тестовом двойнике/прокси.
  - `InsecureKeyLengthWarning` для JWT в тестах.
    - Не влияет на логику, но в prod нужно убедиться, что `SECRET_KEY` длиной не менее 32 байт.
- `ruff check app tests`: 97 ошибок, перечислены в `ANALYSIS.md`.

### 3.2 Frontend
- `eslint`: 37 проблем.
- `vitest`: 5 провалов.
- `tsc`: успех.
- `dist` уже коммитeн (webapp/dist). Если `src` изменится, `dist` может устареть.
- Рекомендация: добавить в CI шаг `npm run build` и сравнить репозиторий с `dist`, либо исключить `dist` из репозитория и собирать в продакшен в pipeline.

### 3.3 Окружение
- GitHub Actions запускает backend и webapp только по патчам их директорий.
- `webapp` использует Node 24, `backend` — Python 3.11.
- Перекрестные зависимости: `webapp` зависит от OpenAPI spec backend, но не запускает backend в CI e2e; `test:e2e` выключен для `mu_ivan/mu_petr` because `testIgnore`.

## 4. Рекомендации по исправлению

1. Backend:
   - Исправить неисправные квадраты в `history.py`.
   - Убрать `print(DEBUG)` в `projects.py`.
   - Исправить `Task` дублирование полей и `request_cancel` логику.
   - Исправить `RWLock` реентерабельность или запретить повторный захват.
   - Исправить `add_file` перегрузки в `paperqa_service.py`.
   - Исправить `rag_retrieval.py` лишние `restore_state`.
   - Исправить `compile_manuscript` (проверка `quality_report` на `None`).
   - Добавить тесты для `history`, `citation_guard`, `grounding`, `tasks`, `backup`.
2. Frontend:
   - Исправить `NavSection.tsx`: вынести `useState` из ветки `hasChildren`.
   - Исправить `any` в `CommandPalette`, `queries.ts`, `chat/ChatTab`.
   - Удалить неиспользуемые импорты: `IconSettings`, `Button`, `defaultIcons`, `IconUserCircle`, `activeProjectId`, `lang` и т.д.
   - Исправить ESLint `any` в `DocumentsTab.tsx` и `ProjectsTab.tsx`.
   - Исправить 4 теста `maintenance.test.tsx` и 1 тест `projects.test.tsx`.
   - Добавить `afterEach` для очистки `sessionStorage`/`localStorage` в тестах.
   - Убрать `dist` из git или синхронизировать его сборку.
3. CI:
   - Добавить проверку `npm run build` как блокирующий шаг.
   - Добавить в `test:e2e` только тесты, готовые к jsdom/браузеру.
   - Добавить в `pytest` шаг по очистке предупреждений или исключить их из билда, пока они не будут проверенны.

## 5. Файл-сводка

- `ANALYSIS.md`: полный отчёт по приложению.
- `ESLINT_VITEST.md`: данный файл.
