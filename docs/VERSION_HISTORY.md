# История версий разделов: варианты работы и целостное правило

Дата: 2026-11-20. Область: `backend/app/services/history.py`,
`backend/app/services/projects.py`, `backend/app/services/section_agent.py`,
`backend/app/services/tasks.py` (генерация), `backend/app/api/projects.py`.

Цель документа — фиксировать **все варианты** работы с историей версий разделов
(SectionPlan + SectionVersion) одним неспортивным правилом и предложить
конечную схему, сравнянную с текущей реализацией.

---

## 1. Текущая модель данных

### 1.1 SectionPlan (жизненный цикл раздела)

| Статус | Значение | Когда выставляется |
| --- | --- | --- |
| `pending` | ожидает генерации | план создан, версий нет (или генерация «пустая»: «нет источников») |
| `in_progress` | генерируется / редактируется | создана ветка (`create_branch`) |
| `review` | на ревью у автора | после генерации, перевода, ручной правки, отката, слияния — новый `draft` стал текущим |
| `approved` | одобрен, можно переводить / включать в сборку | после `approve_version` |

### 1.2 SectionVersion (состояние конкретной версии)

| Статус | Значение | Когда выставляется |
| --- | --- | --- |
| `draft` | черновик (только что сгенерирован / переведён / откачен / слит) | создание версии: генерация, перевод, ручная правка (новый), rollback, branch, merge, «пустая» генерация |
| `review` | на ревью | объявлен, но **нигде в текущих переходах не применяется** (кандидат на рефакторинг статуса) |
| `approved` | одобрен автором | `approve_version`: новая версия → `approved`, план → `approved` |
| `superseded` | заменён новой версией (при генерации) | `_save_version`: предыдущая текущая → `superseded` |
| `archived` | была одобрена, но перестала быть текущей (заменена другой одобренной) | `approve_version`: старый текущий `approved` → `archived` |

`SectionVersion` также хранит `parent_version_id` (дерево версий) и
`current_version_id` на уровне плана — «текущая версия» определяет, какая версия
читается сборщиком рукописи.

---

## 2. Все варианты работы с историей версий

### A. Генерация раздела (generate-async / generate-v2 / «пустая»)

1. Создаётся новая `SectionVersion` со статусом **`draft`**.
2. Если был текущий — он переводится в **`superseded`** (`_save_version`).
3. `plan.current_version_id` := новый; `plan.status` := `review`.
4. «Пустая» генерация (нет источников): версия `draft` с `quality_report.passed=false`,
   `plan.status` := `pending`.

### B. Перевод версии на другой язык (translate / translate-v2)

1. Создаётся новая `SectionVersion` статуса **`draft`** (язык = целевой,
   `source_language` = язык оригинала; `parent_version_id` = source).
2. **Реализовано (2026-11-20):** перевод сразу становится текущей версией —
   `plan.current_version_id := new version`, `plan.status := review`.
3. При одобрении перевода: approve переводит его в `approved`, переключает
   `current` на перевод и архивирует прежний одобренный source — перевод
   попадает в сборку.

### C. Ручная правка текста (save content)

1. Если текущая версия — `draft`: текст правится **на месте** (content/word_count).
2. Иначе: создаётся **новая версия `draft`** (родитель = current), `plan.current` := новая,
   `plan.status` := `review`.

### D. Откат к версии (rollback)

1. Создаётся **копия** версии-мишени: статус **`draft`**, `parent_version_id` = target.
2. `plan.current_version_id` := новая (draft); `plan.status` := `review`.
3. Старая версия **не меняется** (если была `approved` — остаётся `approved`).

### E. Создание ветки (create_branch)

1. Создаётся копия базовой версии: статус **`draft`**, `parent_version_id` = base.
2. `plan.current_version_id` := новая; `plan.status` := `in_progress`.

### F. Слияние веток (merge_branches)

1. Создаётся новая версия (`draft`) — LLM-merge или простое слияние;
   `parent_version_id` := target.
2. `plan.current_version_id` := новая; `plan.status` := `review`.

### G. Одобрение версии (approve)

1. Версия → **`approved`**.
2. `plan.current_version_id` := одобренная версия; `plan.status` := `approved`.
3. Если `current` ≠ одобренной и стоял `approved` — он → **`archived`**.

---

## 3. Ответы на вопросы

### 3.1. Как попадает сгенерированный/переведённый материал в историю и с каким статусом?

- Ген/перевод/правка/rollback/branch/merge → версия **`draft`**, текущая (или новая для draft-правки).
- При этом старая текущая при генерации → `superseded`.

### 3.2. Когда меняется статус?

- Создание версии → `draft`.
- Генерация (новая версия) → старая current: `superseded`; новая: `draft`.
- Одобрение → версия `approved`, план `approved`, старый одобренный current → `archived`.

### 3.3. Может ли быть несколько версий со статусом `Одобрен` или `Черновик`?

- **Черновик:** да — история дерева допускает много `draft` (потомки rollback/branch/merge/translate, а также цепочка генераций).
- **Одобрен:** для одного плана валидна схема «один текущий `approved` + архивные»: approve переводит старый `approved`-current в `archived`, поэтому одновременно два «активных» одобренных одного раздела не должны существовать; архивных же может быть несколько. Сверху в разных ветках тоже не должно нарушаться правилом approve.

### 3.4. Что, если одобрить версию со статусом `Архив`?

Текущая реализация **не блокирует** approve по статусу: approve любой версии переводит её в `approved` и переключает `current`. То есть approve-from-archive работает как «восстановление/переназначение одобрения». В предложенной схеме это сохраняется как явное правило.

### 3.5. Какой статус у материала, входящего в сборку?

`compile_manuscript` (strict): берёт `plan.current_version_id`; нет версии → warning «нет версии»; версия есть, но `status != approved` и без `include_unapproved` → warning «не одобрен (статус …)» и **не включается**. В сборку попадает current version со статусом `approved` (или любой — при `include_unapproved=true`).

**Вход в сборку после одобрения перевода:** approve перевод → перевод `approved` + current → сборка включает перевод; source (если был одобрен) → `archived`.

---

## 4. Предложенное (целевое) правило работы с историей версий

### 4.1. State machine для версии

```
            ┌──────────────► draft ──approve──► approved ──(замена новым approve)──► archived
            │             │  ▲                                 ▲
            │             │  └──────────── superseded ◄┘ (generation)
            │             │
            └─────────────┴─────► draft (rollback/branch/merge/translate/new draft)
```

- `draft → approved`: основной путь принятия (черновик → одобрение).
- `draft → superseded`: старая текущая заменена новой генерацией.
- `approved → archived`: одобренная версия перестала быть текущей (новое одобрение).
- `approved` (archived) → `approved` (restore): approve-from-archive.

### 4.2. Правила ввода в сборку (жёсткое)

- Сборка (strict) использует **только** `current_version_id` версии со статусом `approved`.
- `include_unapproved=true` — осознанный обход для разработки/тестирования (запрещён в проде по умолчанию).
- После перевода текущей версией становится перевод (`draft`, план → `review`); после approve перевода — перевод `approved` и сборка включает его, source → `archived`.

### 4.3. Правила переходов плана

- `pending → in_progress → review → approved` — цепочка жизненного цикла раздела.

### 4.4. Границы/валидации (рекомендации)

1. `approve` принимает версию из `draft` (норм) или из `archived` (restore) — не из `superseded`.
2. Rollback: стару approved-текущую логично переводить в `archived`? **Решение:** оставить как есть (версия-мишень остаётся approved в истории, current — новый draft); фиксировать в истории через `parent_version_id`. Но тогда «approved» = «одобренный и в сборке» только при current — это уже обеспечивается проверкой в compile.
3. Translation: обновлять `plan.current_version_id`? **Решение:** да — после перевода current должен указывать на перевод (для целевого языка), иначе «текущая версия» остаётся источником. **Реализовано** (2026-11-20, `SectionTranslator.translate`): после создания перевода `plan.current_version_id := new version`, `plan.status := review`.

---

## 5. Сравнение «сейчас» и «предложение»

| # | Вопрос / поведение | Сейчас | Предложение |
| --- | --- | --- | --- |
| 1 | Как попадает материал в историю | draft через все creation-пути | без изменений, фиксация |
| 2 | Когда меняется статус | draft/superseded/approved/archived по триггерам | те же переходы + валидации approve |
| 3 | Несколько Одобрен/Черновик | да (много draft; один current approved) | фиксировать инвариант |
| 4 | Approve версии со статуса `Архив` | разрешено, работает как restore | разрешить явно + документировать |
| 5 | Статус при сборке | approved (strict) / любой (include_unapproved) | без изменений, фиксация |
| 6 | Approve из `superseded` | не запрещено (не должно происходить валидно) | запретить в v1 |
| 7 | Translation → current | обновляет current (с 2026-11-20) | без изменений, фиксация |
| 8 | VersionStatus.review | объявлен, но не используется | либо убрать, либо использовать для «на ревью» версий |

---

## 6. Итоговое правило (резюме)

1. **Создание версии** (generate/translate/save/rollback/branch/merge) → `draft`; старая current при замене генерацией → `superseded`.
2. **Одобрение** → version `approved`, plan `approved`; старый approved-current → `archived`; approve допускает `draft`→`approved` и `archived`→`approved` (restore).
3. **Сборка** строгая берёт `current_version_id` со статусом `approved`; иначе — warning и пропуск.
4. **История** — дерево через `parent_version_id`; «текущая» версия — через `plan.current_version_id`.

---

## 7. Удаление устаревшего совместимого слоя (2026-11-20)

Проект находится в разработке, устаревших данных нет: все проекты создаются через API
сразу с планом разделов. Поэтому поддержка старой модели полностью убрана:

- удалены `POST /section-plans/sync`, `POST /generate`, старый
  `POST /sections/{name}/translate` и `GET /versions{,/diff}`;
  скрипт `backend/scripts/sync_section_plans.py` удалён;
- ETA генерации (`GET /eta`) считается по `SectionVersion.seconds` с группировкой
  по типу плана, а не по старым `project_versions`;
- `generate-async` работает через `ProjectService.generate_section_v2`
  (SectionAgent) и возвращает в `task.result` словарь с `section`, `content_md`,
  `word_count`, `sources`, `citations_ok`, `from_cache`, `seconds`;
- убраны `ensure_section_plans`, `_compile_manuscript_legacy`, зеркало записей в
  `project.sections` и fallback-чтение `project.sections` / `project.versions`;
- стартовый план разделов создаётся при `POST /projects` методом
  `ProjectService.set_section_plans` — это инициализация нового проекта, а не
  миграция;
- экспорт (`app/services/export.py`) и прогресс проекта читают только
  `section_plans` + текущие `section_versions`.

Внутренний тип `GenerationResult` остался в `app/services/generation.py` как
результат работы LLM внутри `SectionAgent` — это не совместимый слой.
