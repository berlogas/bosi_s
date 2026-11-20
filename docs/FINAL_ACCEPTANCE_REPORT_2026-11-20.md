# Финальный отчёт: приёмочный прогон и удаление совместимого слоя

Дата: 2026-11-20. Репозиторий: `boasi_s`.

## 1. Что проверялось

Полный пользовательский цикл средствами приложения (HTTP API и штатные скрипты,
без прямой правки БД):

глобальные данные → пользователь → сессия → данные сессии → проект со стилем
и планом разделов → генерация разделов → рукопись → экспорт.

Драйвер: `.tmp/acceptance/run_acceptance.py`, состояние: `.tmp/acceptance/state.json`,
журнал: `.tmp/acceptance/run.log`. Подробный пошаговый отчёт —
`docs/ACCEPTANCE_RUN_2026-11-19.md`.

## 2. Результат приёмки

- Ошибок драйвера, упавших задач и падений API: **0**.
- Итоговая рукопись: **7 разделов**, **1739 слов**, источников **5**.
- Экспорт: `final_article.md` (24304 B), `final_article.docx` (43620 B),
  `final_article.zip` (49294 B) — все валидны, docx открывается как OOXML.
- Использованные тестовые данные: `acc_admin`/`AcceptAdmin-2026`, `researcher`/
  `AcceptUser-2026`, сессия `58f70ca8-7013-450b-a57b-9f3b4c16389f`, проект
  `ad2b9ca1-6d69-41d5-b4a7-f1b2019e31dd`, стиль `sound_science`.

## 3. Исправленные дефекты

| № | Дефект | Исправление |
| --- | --- | --- |
| 1 | План для `sound_science` включал клинические разделы | план строится только по `default_template` |
| 2 | `reset_registry()` подменял объект реестра задач; `GET /api/tasks/{id}` → 404 | реестр очищается на месте (`TaskRegistry.clear()`) |
| 3 | Фоновая генерация теряла правки плана после закрытия request-сессии | фон работает в своей сессии и перечитывает ORM-объекты |
| 4 | `approve_version` падал с `NameError` (нет импорта `SectionStatus`) | импорт добавлен, одобрение всех разделов проверено |
| 5 | Перевод раздела не становился текущим | `SectionTranslator.translate` обновляет `current_version_id` и статус плана |
| 6 | Подписи «новая система» в UI и statuses на английском | «План разделов», статусы «Ожидает/В работе/На ревью/Утверждён» |
| 7 | Объём разделов не зависел от стиля журнала | `StyleTemplate.word_counts` из `styles.toml`, fallback 500 слов |
| 8 | `approve`/`rollback`/`translate` не обновляли кэш истории в UI | инвалидация ключей `section-plan-history`, `project-section-versions`, `manuscript` |
| 9 | `rollback`/`branch`/`merge` падали из-за вызова `new_id(ctx)` | переход на штатный `new_id()` |
| 10 | Таймаут клиента перевода был 300 с при фактическом времени >300 с | таймаут повышен до 600 с |

## 4. Удаление совместимого слоя (2026-11-20)

Проект в разработке, устаревших данных нет — поддержка старой модели полностью
убрана:

- эндпоинты `POST /section-plans/sync`, `POST /generate`,
  `POST /sections/{name}/translate`, `GET /versions` и `GET /versions/diff`;
- скрипт `backend/scripts/sync_section_plans.py`;
- сервисные методы `sync_project_sections_to_plans`, `ensure_section_plans`,
  `generate_section`, `_save_version`, `_write_into_plan`, `_find_cached`,
  `_build_prompt`/`_complete`, `_compile_manuscript_legacy`,
  `SectionAgent._sync_to_project_json`;
- зеркало записей в `project.sections`, fallback-чтение `project.sections` и
  `project.versions` в прогрессе, экспорте и сборке рукописи;
- клиентские методы `generate`, `syncSectionPlans`, `translateSection` и кнопка
  «Синхронизировать из JSON».

Вместо этого:

- стартовый план разделов создаётся при `POST /projects` через
  `ProjectService.set_section_plans`;
- фоновая генерация работает через `generate_section_v2` → SectionAgent и
  возвращает в `task.result` `section`, `content_md`, `sources`, `word_count`,
  `citations_ok`, `from_cache`, `seconds`;
- ETA считается по `SectionVersion.seconds`, группировка по типу плана;
- OpenAPI-контракт (`webapp/openapi/spec.json`) и `webapp/src/api/schema.ts`
  перегенерированы.

## 5. Верификация после очистки

- backend: полный прогон `pytest tests` — **752 passed**, 2 skipped, 2 deselected,
  0 failures.
- проекты/экспорт: `tests/test_projects_api.py` — 41 passed,
  `tests/test_export.py` — 31 passed;
- ruff (F401/F821) на изменённых файлах — без ошибок;
- frontend: `tsc -b`, `eslint` (0 errors, 1 существующее предупреждение React
  Compiler), `vitest` проектов — 28 passed;
- OpenAPI-контракт совпадает с кодом;
- кнопка «Перегенерировать устаревшие» исправлена: корректный снимок контекста
  генерации, фоновые задачи с прогрессом, регрессионные тесты backend/frontend;
- создание резервной копии в «Администрировании» показывает процент и этап
  (снимок БД, архивирование с счётчиком файлов, контрольная сумма, ротация),
  описание добавлено в `docs/ADMIN_GUIDE.md`;
- контейнеры пересобраны (`docker compose up -d --build backend webapp`):
  backend `healthy`, webapp отвечает 200; `GET /api/health` → 200; в открытом
  OpenAPI 100 путей, удалённых эндпоинтов нет, `/progress` на месте.

## 6. Итог

Полный приёмочный цикл и финальная очистка завершены. Все проверки зелёные,
регрессий в пользовательском сценарии нет. Коммит очистки: см. историю git
(`refactor: remove legacy project-section compatibility layer`).
