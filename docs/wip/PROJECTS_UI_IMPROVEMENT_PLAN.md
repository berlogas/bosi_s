# План улучшения UI «Сессия → Проекты»

> Создан на основе аудита текущего кода (`webapp/src/features/projects/ProjectsTab.tsx` и связанных файлов).
> Статусы: `[ ]` — не начато, `[~]` — в процессе, `[x]` — готово.

---

## Этап 1: Быстрые выигрыши (1-2 дня)

### 1.1 Заменить кастомный прогресс-бар на Mantine `Progress`
- [x] Найти рендер прогресс-бара в `ProjectEditor` (строки ~350-370)
- [x] Заменить `div` + inline styles на `<Progress value={percent} size="sm" color="blue" striped />`
- [x] Убрать дублирующиеся `aria-*` атрибуты (Mantine добавит сам)

### 1.2 Добавить иконки из `@tabler/icons-react` во все кнопки/заголовки
- [x] Установлен `@tabler/icons-react` (уже в зависимостях)
- [ ] Добавить иконки:
  - [x] Создание проекта: `IconPlus`
  - [x] Удаление: `IconTrash`
  - [x] Выгрузка: `IconDownload`
  - [x] История: `IconHistory`
  - [x] Генерация: `IconSparkles`
  - [x] Анализ: `IconSearch`
  - [ ] Перевод: `IconWorld`
  - [x] Правила оформления: `IconFileText`
  - [x] Статусы: `IconClock` (planning), `IconPencil` (drafting), `IconEye` (reviewing), `IconCheck` (done)
  - [ ] Роли документов: `IconBook` (reference), `IconDatabase` (data), `IconFilePencil` (draft), `IconSettings` (style_guide)
  - [x] Экспорт форматы: `IconFileWord`, `IconFileCode`, `IconArchive`

### 1.3 Исправить hover-стили списка проектов
- [x] Убрать `onMouseEnter` / `onMouseLeave` inline-хендлеры у `Paper`
- [x] Использовать токены темы: `var(--mantine-color-primary-filled)` (CSS transition уже был)

### 1.4 Добавить `EmptyState` для списка проектов и разделов
- [x] Для проектов: иллюстрация `IconFilePlus`, заголовок «Проектов пока нет», описание, кнопка «Создать проект» (фокус на поле названия)
- [x] Для разделов: когда `sections.data?.length === 0` — показать «Разделов нет. Сгенерируйте или создайте вручную.»

### 1.5 Сгруппировать настройки проекта в `Accordion`
- [x] В `ProjectEditor` обернуть: язык, стиль журнала, правила оформления, экспорт → в `<Accordion multiple>` с панелями «Основные настройки», «Правила оформления журнала», «Экспорт»

---

## Этап 2: Навигация (2-3 дня)

### 2.1 Расширить `SessionBreadcrumb` с контекстом проекта/раздела
- [x] Создать `BreadcrumbContext` и `BreadcrumbProvider`
- [x] Обновить `SessionBreadcrumb` для отображения проекта/раздела
- [x] Обернуть `Outlet` в `BreadcrumbProvider` в `SessionPage`
- [x] В `ProjectsTab` обновлять контекст при выборе проекта/раздела
- [x] В `SessionBreadcrumb` показывать: `Панель / Сессия «...» / Проекты / «Проект» / Раздел «...»`

### 2.2 Поиск/фильтр проектов над списком
- [x] Добавить `TextInput` с `leftSection={<IconSearch />}` над списком
- [x] Фильтрация по `title` + `sections[].name` (мгновенно, без debounce)
- [x] Показывать счётчик: «Показано 5 из 12 проектов»

### 2.3 Горячие клавиши
- [x] `Ctrl+N` — фокус на поле названия нового проекта
- [x] `Ctrl+S` — сохранить текущий раздел (если dirty)
- [ ] `Ctrl+Enter` — сгенерировать раздел (если фокус в редакторе)
- [x] `Esc` — закрыть Drawer/Modal, свернуть аккордеон
- [ ] Стрелки `←/→` — навигация по табам сессии (chat/documents/projects/notes)

---

## Этап 3: Редактор и генерация (1 неделя)

### 3.1 Тулбар CodeMirror (форматирование, заголовки, списки)
- [x] Добавить панель кнопок над редактором: H2, H3, Bold, Italic, List (ul/ol), Quote, Code, Link, Table
- [x] Использовать `editor.dispatch({ changes: ... })` для вставки markdown-разметки
- [x] Горячие клавиши: `Ctrl+B`, `Ctrl+I`, `Ctrl+K` (ссылка), `Ctrl+Shift+L` (список)

### 3.2 Word count в футере редактора
- [x] Показывать: «Слов: 1234 | Символов: 7890 | Строк: 56»
- [x] Обновлять в реальном времени (debounce 300мс)

### 3.3 История версий с нормальным diff
- [ ] Подключить `diff-match-patch` или `@uiw/react-diff`
- [ ] В `VersionHistoryDrawer` заменить текстовый diff на построчный с подсветкой (+ зелёное, - красное)
- [ ] Добавить кнопку «Восстановить эту версию» (PATCH /sections/{name} с content из версии)

### 3.4 Вкладки генерации / анализ / история генераций
- [x] В `GeneratePanel` заменить единую панель на `Tabs` с тремя вкладками
- [x] История генераций: колонки — Дата, Kind, Статус, Токены, Время, Действия (Повторить, Посмотреть промпт)

### 3.5 Индикатор токенов/стоимости
- [ ] Убрано по запросу пользователя
- [ ] При ошибке лимита — тост с ссылкой на биллинг

---

## Этап 4: Документы и полировка (3-4 дня)

### 4.1 Виртуализация + поиск в списке документов
- [x] В `ProjectDocumentsPanel` для `free` документов добавить `TextInput` поиск
- [x] При >50 документах — `@tanstack/react-virtual` для списка чекбоксов

### 4.2 Inline-смена роли документа
- [x] В строке привязанного документа добавить `Select` с ролями (reference/data/draft/style_guide)
- [x] При смене — PATCH unbind + bind с новой ролью (или отдельный эндпоинт, если есть)

### 4.3 Превью документа в Drawer
- [x] Клик по строке документа (привязанного или свободного) → `Drawer` с превью
- [x] Markdown → `MarkdownText`, PDF → `<iframe>`/PDF.js, CSV → таблица (первые 100 строк)

### 4.4 Drag-and-drop переупорядочивание проектов
- [x] Подключить `@dnd-kit/core` + `@dnd-kit/sortable`
- [x] `SortableContext` вокруг списка проектов
- [x] При завершении — PATCH `/projects/{id}` с новым `order` для затронутых проектов

### 4.5 Анимации (framer-motion)
- [x] Появление карточек проектов: `AnimatePresence` + `motion.div` с `initial={{ opacity: 0, y: 10 }}`
- [x] Раскрытие аккордеонов: `height: 'auto'` анимация (частично, в документах)
- [x] Открытие Drawer/Modal: уже есть в Mantine, проверена плавность
- [x] Тосты: `framer-motion` для slide-in (в документах и превью)

---

## Этап 5: Архитектура (параллельно, рефакторинг)

### 5.1 Разбить `ProjectsTab.tsx` на модули
```
features/projects/
├── components/
│   ├── ProjectList.tsx
│   ├── ProjectCard.tsx
│   ├── ProjectEditor.tsx
│   ├── GeneratePanel.tsx
│   ├── SectionsList.tsx
│   ├── SectionAccordionItem.tsx
│   ├── VersionHistoryDrawer.tsx
│   ├── ProjectDocumentsPanel.tsx
│   ├── CodeMirrorSection.tsx
│   ├── ExportPanel.tsx
│   ├── EmptyState.tsx
│   ├── Toolbar.tsx
│   ├── SortableProjectItem.tsx
│   ├── GenerateResultView.tsx
│   ├── GenerationHistoryPanel.tsx
│   ├── StyleGuideSelector.tsx
│   └── HowToPanel.tsx
├── hooks/
│   ├── useProjects.ts
│   ├── useProjectEditor.ts
│   ├── useSectionDrafts.ts
│   └── useGeneration.ts
├── ProjectsTab.tsx (тонкий контейнер)
└── index.ts
```

### 5.2 Вынести хуки в `features/projects/hooks/`
- [x] `useProjectDrafts` — управление черновиками (localStorage + автосейв)
- [x] `useSectionEditor` — состояние редактора, сохранение, грязные флаги
- [x] `useGeneration` — генерация, анализ, история, токены
- [x] `useProjects` — проекции select для оптимизации списка

### 5.3 Добавить `select` в TanStack Query хуки
- [x] В `queries.ts` для `useProjects` добавить `select` проекции только нужных полей для списка (через `useProjects` хук)
- [x] Аналогично для `useSections`, `useProjectDocuments`

### 5.4 Покрыть ключевые сценарии e2e тестами (Playwright)
- [ ] Создание проекта → генерация раздела → сохранение → экспорт
- [ ] Переключение проектов, мобильный режим
- [ ] История версий: генерация → открытие истории → diff → восстановление

---

## Метрики для отслеживания

| Метрика | Baseline | Target | Измерение |
|---|---|---|---|
| Time to first project creation | ~4 клика | 2 клика | Playwright тест |
| Time to generate section | ~6 кликов | 3 клика | Playwright тест |
| A11y score (axe-core) | ~70 | >95 | CI pipeline |
| Bundle size (projects chunk) | ~180 KB gzip | <120 KB | `vite build --report` |

---

## Лог выполнения

### 2024-11-05 — Начало работы
- [x] Аудит кода завершён
- [x] План сохранён в `PROJECTS_UI_IMPROVEMENT_PLAN.md`
- [x] Этап 1 — Быстрые выигрыши
- [x] Этап 2 — Навигация (2.1, 2.2, 2.3 частично)
- [ ] Этап 2.3 — горячие клавиши (Ctrl+Enter, стрелки ←/→)

### 2024-11-06 — Этап 4: Документы и полировка
- [x] 4.1 Виртуализация + поиск в списке документов
- [x] 4.2 Inline-смена роли документа
- [x] 4.3 Превью документа в Drawer
- [x] 4.4 Drag-and-drop переупорядочивание проектов
- [x] 4.5 Анимации (framer-motion) для документов, превью, карточек

### 2024-11-06 — Этап 5: Архитектура (рефакторинг)
- [x] 5.1 Разбит `ProjectsTab.tsx` на модули в `components/` и `hooks/`
- [x] 5.2 Созданы хуки: `useProjectDrafts`, `useSectionEditor`, `useGeneration`, `useProjects`
- [x] 5.3 Добавлены проекции `select` в TanStack Query хуки через `useProjects`
- [x] `ProjectsTab.tsx` стал тонким контейнером (~150 строк вместо 2100+)

