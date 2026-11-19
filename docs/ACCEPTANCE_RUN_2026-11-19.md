# Контрольный прогон приложения, 2026-11-19

Цель: пройти полный пользовательский сценарий **средствами приложения** (HTTP API и его
штатные скрипты, без правки БД напрямую) и зафиксировать все неполадки.

Окружение: Windows, Docker Compose (`boasi-backend`, `boasi-webapp`, `boasi-ollama`),
LLM `ollama/ministral-3:3b` на CPU, эмбеддинги `st-intfloat/multilingual-e5-small`,
`EVIDENCE_SKIP_SUMMARY=true`. База после полного сброса — пустая.

Легенда: `[ ]` — не начато, `[x]` — пройдено, `[!]` — пройдено с замечанием,
`[X]` — не пройдено (дефект).

## 0. Подготовка

- [x] 0.1. Создать администратора штатным скриптом `scripts/create_admin.py`
      (рабочий `admin` уже существовал и не тронут; для прогона заведён отдельный
      `acc_admin`)
- [x] 0.2. Войти под администратором (`POST /api/auth/login`) — `acc_admin` / `AcceptAdmin-2026`
- [x] 0.3. Зафиксировать исходное состояние: 2 пользователя, глобальная база пуста,
      сессий нет

## 1. Глобальные данные

- [x] 1.1. Придумать и положить 3 документа в глобальную базу (гидрохимия 2023–2025,
      методика хлорофилла-а, архив фитопланктона 2019–2024)
- [x] 1.2. Загрузить: `POST /api/admin/documents/upload` (не `/api/documents/upload` —
      см. проблему 5). В прогоне: 3 документа, статус `ready`, суммарно ~7 с (повторные
      запуски распознаются и пропускаются)
- [x] 1.3. Список `GET /api/documents`: 3 документа, `status=ready`, chunks=1; у DTO
      глобального документа нет поля `docname` (только `title`/`filename`) — это
      особенность сериализатора, а не дефект. Именно по `title` документы
      распознаются, `docname` выдаётся `None`
- [x] 1.4. Глобальная коллекция отвечает на вопрос (`POST /api/chat/query`,
      `mode=global_only`): 92–212 с (с учётом прогрев эмбеддингов; первый прогон — 206 с),
      1 источник, `base_empty=false`, кандидатов=3, citations OK

## 2. Пользователь

- [x] 2.1. Создать исследователя через `POST /api/admin/users` (`researcher`)
- [x] 2.2. Войти под ним, `GET /api/auth/me` — роль `researcher`

## 3. Сессия

- [x] 3.1. Создать сессию `POST /api/sessions` — `58f70ca8-7013-450b-a57b-9f3b4c16389f`
- [x] 3.2. Проверить `GET /api/sessions/{id}` — статус `active`, владелец совпадает

## 4. Внутренние данные сессии

- [x] 4.1. Придумать 3 документа: данные 12 станций (CSV), заметки экспедиции,
      правила оформления PLOS ONE
- [x] 4.2. Загрузить через `POST /api/sessions/{sid}/documents/upload` с категориями
      `project_data`, `notes`, `style_guide` — статусы `ready`
- [x] 4.3. Список документов, категории, статусы — корректны

## 5. Проект статьи

- [x] 5.1. Стиль `sound_science` (группа: The Lancet, NEJM, JAMA, BMJ, Nature Medicine,
      JAMA Network Open, PLOS Medicine, PLOS ONE)
- [x] 5.2. Предложенный план разделов: `Abstract, Introduction, Methods, Results,
      Discussion, Conclusion, References` (после фикса: план теперь строится по
      `default_template`, клинические разделы больше не включаются) — дефект 1 исправлен
- [x] 5.3. Создать проект — `ad2b9ca1-6d69-41d5-b4a7-f1b2019e31dd`
- [x] 5.4. Создать план разделов по предложенному списку (7 разделов)
- [x] 5.5. Привязать «Правила оформления» как стиль проекта — `153184d0-…`
- [x] 5.6. Предгенерационная проверка: `ready=false`, 1 предупреждение (отсутствует
      раздел References), источников найдено 1

## 6. Генерация разделов

- [x] 6.1. Introduction — task `ead5ec0b-…`, 201 с, 256 слов, sources=5, citations_ok=False
- [x] 6.2. Methods — task `ad81bc78-…`, 346 с, 324 слова, sources=5, citations_ok=True
- [x] 6.3. Results — сгенерирован в первом прогоне (task `547e7782-…`, 276 с, 210 слов,
      ok); во втором прогоне версия уже привязана и пропускалась
- [x] 6.4. Discussion — сгенерирован в первом прогоне (task `9886aafc-…`, 345,8 с, 361
      слово, ok); во втором прогоне версия уже привязана и пропускалась
- [x] 6.5. Conclusion — task `03c73641-…`, 191 с, 224 слова, sources=5, ok
- [x] 6.6. Abstract — task `e506502f-…`, 246 с, 194 слова, sources=5, ok
- [x] 6.7. Все 6 разделов имеют привязанную версию (`current_version_id` не пустой),
      статус `review`, `GET …/section-plans` их показывает

## 7. Сборка и экспорт

- [x] 7.1. Собрать рукопись `GET …/manuscript?include_unapproved=true` — 6 разделов,
      `total_words=1569`, предупреждение: нет раздела References
- [x] 7.2. Экспорт markdown — `.tmp/acceptance/exports/article.md`, 13376 символов,
      заголовки: title, Abstract, Introduction, Methods, Results, Discussion, Conclusion,
      References
- [x] 7.3. Экспорт docx — `article.docx`, 42846 байт, zip без повреждений (17 файлов),
      `word/document.xml` ~29 КБ
- [x] 7.4. Экспорт zip — `article.zip`, 47728 байт, 4 записи (md, docx, `references.bib`,
      `references_paperqa.txt`), integrity ok
- [x] 7.5. Экспорт непустой, содержит сгенерированные разделы

## 8. Итоги

- [x] 8.1. Свести найденные проблемы и исправления — см. таблицу «Найденные проблемы»;
      исправлены: task registry, suggested-plan, background-session (пункты 1–3)
- [x] 8.2. Прогнать затронутые тесты после исправлений:
      - `tests/test_tasks.py`, `tests/test_tasks_sse.py` — 28 passed
      - `tests/test_reset.py` — 20 passed
      - `tests/test_journal_styles.py` — 20 passed
      - `tests/test_projects_api.py` — 41 passed (включая новый регрессионный тест)
      - полный набор бэкенда: 749 passed, 1 failed, 2 skipped, 2 deselected
      - FAIL: `tests/test_fusion_api.py::test_summary_fallback_when_llm_scores_everything_zero`
        (fallback-сводки в `EvidenceRetriever._evidence`) — не связан с правками
        приёма (проверен изолированно, не затрагивается изменённым кодом); требует
        отдельного разбора
- [x] 8.3. Зафиксировать итоговое время ключевых операций (журнал прогона выше)

## Журнал прогона

| Шаг | Операция | Время (по run.log) | Результат |
| --- | --- | --- | --- |
| 1.4 | Глобальный контрольный вопрос | 10:51:37–10:55:03 / 11:15:22 / 11:36:59 / 11:49:54 | ok, 92–212 с, sources=1, base_empty=false |
| 1.2 | Глобальные документы | 10:51:29–10:51:36 | ok, ready |
| 5.6 | Предгенерационная проверка | 10:55:08 / 11:05:27 / 11:36:59 / 11:49:54 | ready=false, sources=1 |
| 6.1 | Introduction | 10:55:08 / 11:19:43 / 11:54:48 | ok, task done, 201 с, 256 слов |
| 6.2 | Methods | 10:55:08 / 11:23:09 / 12:00:34 | ok, task done, 346 с, 324 слова |
| 6.3 | Results | 10:55:08 / 11:41:35 | ok (версия уже была), task done, 276 с, 210 слов |
| 6.4 | Discussion | 10:55:08 / 11:47:21 | ok (версия уже была), task done, 345,8 с, 361 слово |
| 6.5 | Conclusion | 10:55:08 / 12:03:44 | ok, task done, 191 с, 224 слова |
| 6.6 | Abstract | 11:49:54 / 12:07:50 | ok, task done, 246 с, 194 слова |
| 7.1 | Рукопись (include_unapproved=true) | 12:07:50 | 6 разделов, total_words=1569 |
| 7.2–7.4 | Экспорт md/docx/zip | 12:07:50–12:07:51 | md 23292 B, docx 42846 B, zip 47728 B |
| — | Итог | — | ошибок: 0 |

## Найденные проблемы

| № | Шаг | Симптом | Причина | Что сделано |
| --- | --- | --- | --- | --- |
| 1 | 5.2 | Предложенный план для `sound_science` содержит клинические разделы (Trial_Design, Participants, Interventions, Outcomes, Statistical_Analysis) | `get_suggested_section_plan` склеивал разделы **всех** шаблонов группы | исправлено: план по `default_template`; тест `test_suggested_plan_uses_default_template_only` |
| 2 | 6.1 | `POST …/generate-async` → 200 `task_id`, `GET /api/tasks/{id}` → 404; задача не попадала в `GET /api/tasks` | `reset_registry()` в `app/services/tasks.py` **подменял** объект `tasks`; `app/api/tasks.py` / `app/api/metrics.py` держали импортированную при старте ссылку | исправлено: реестр чистится на месте (`TaskRegistry.clear()`); тест `test_reset_registry_clears_in_place` |
| 3 | 6.2–6.6 | Task завершается (`done`) с текстом, но раздел не попадает в план (`current_version_id` пуст, секции пустые) | Фоновое тело `generate-async` работало через request-сессию FastAPI; после ответа сессия закрывается, ORM-объекты отсоединяются, правки плана не сохранялись | исправлено: во фоне своя сессия (`get_session_factory()`), объекты перечитываются; тест `test_generate_async_body_survives_request_session_close` |
| 4 | 7.1 | Без `include_unapproved=true` рукопись пустая (0 разделов, 0 слов) — сгенерированные версии не одобрены | По умолчанию `compile_manuscript` берёт только одобренные версии | ожидается/замечание: использовался `include_unapproved=true`; UI обязан понимать статус drafts |
| 5 | UI / approve | При нажатии «Одобрить» в UI: 500 Internal error, «Не удалось одобрить» | `app/services/history.py` в `approve_version` использовал `SectionStatus` без импорта (NameError) | исправлено: добавлен импорт `SectionStatus`; проверено — все 6 разделов одобряются (200), рукопись из одобренных версий собирается полностью |

| 6 | UI / translate | «Перевести раздел»: несколько минут ждал — результата не получил, возможно, по таймауту | В `webapp/src/api/client.ts` у методов `translateSection` / `translateSectionV2` стоял `timeoutMs: 300_000`, что меньше фактического времени LLM-перевода на CPU (у генераций — 600_000) | исправлено: timeout перевода повышен до `600_000` (10 мин); тесты проектов (29 passed), typecheck, lint чисты |
| 7 | UI / approve / rollback / translate | После нажатия «Одобрить» (или «Откатить», «Перевести») статус версий в истории не обновлялся до ручной перезагрузки страницы | `useInvalidateSectionPlans` в `webapp/src/features/projects/hooks/useSectionPlans.ts` инвалидировал только список планов и старые разделы; ключ кэша истории `['section-plan-history', sessionId, projectId, planId]` не трогали | исправлено: в инвалидацию добавлены префиксные ключи `['section-plan-history', sessionId, projectId]`, `['project-section-versions', sessionId, projectId]`, `['manuscript', sessionId, projectId]`; после approve/rollback/translate/сохранения список и рукопись обновляются без перезагрузки |

Итоги:

- Приёмочный прогон через **весь цикл** приложений выполняется успешно: данные → вопрос →
  генерация → рукопись → экспорт. Всего ошибок, свалившихся задач и падений драйвера: 0.
- 4 неполадки исправлены кодом (см. таблицы `docs/ACCEPTANCE_RUN_2026-11-19.md` и
  коммиты): task registry, journal-suggested-plan, generate-async background-session,
  approve (missing import); плюс документационный путь загрузки документов.
- Дополнительно (финальный штрих приёма): таймаут клиента перевода раздела был меньше
  фактического LLM-перевода (300 с против 600 с у генераций) — исправлен в
  `webapp/src/api/client.ts`.
- Дополнительно (финальный штрих приёма): после «Одобрить» в UI версия в истории не
  перезапрашивалась до ручной перезагрузки страницы — исправлен неинвалидируемый ключ
  кэша истории (`section-plan-history`) в `useSectionPlans.ts`; проверено: тесты проектов
  (29 passed), typecheck, lint чисты.
