# Implementation Summary: Section Generation Redesign (Phases 1-5)

> Исторический документ (2026-11). С 2026-11-20 эндпоинт
> `POST /section-plans/sync` удалён вместе со всем совместимым слоем: план
> разделов создаётся при создании проекта, генерация идёт только через
> SectionAgent.

## Completed

### Phase 1: Data Model & Migrations ✅
- **New tables** in `backend/alembic/versions/2e4e4ea086df_add_section_plans_versions_language_.py`:
  - `section_plans` — replaces `Project.sections` JSON with proper relational model
  - `section_versions` — version tree with language, parent_version_id, quality_report
  - `project_language_policies` — primary/allowed languages, auto-translate settings, **quality thresholds, max iterations**
  - `terminology_glossary` — project-specific term translations

- **New enums** in `models.py`:
  - `SectionKind` (standard, literature_review, data, discussion, custom)
  - `SectionStatus` (pending, in_progress, review, approved)
  - `VersionStatus` (draft, review, approved, superseded, archived)
  - `TranslationStatus` (pending, in_progress, completed, failed)

- **New models** with relationships:
  - `SectionPlan` → `Project` (many-to-one), `SectionVersion` (one-to-many)
  - `SectionVersion` → `SectionPlan`, `Project`, `ResearchSession`, `User` (+ `cost_usd`, `token_counts`)
  - `ProjectLanguagePolicy` → `Project` (one-to-one) (+ `quality_grounding_threshold`, `quality_completeness_threshold`, `quality_citations_required`, `max_generation_iterations`)
  - `TerminologyGlossary` → `Project` (many-to-one)

- **Migrations applied** to database `data/boasi.sqlite3` successfully

### Phase 2: SectionAgent Service ✅
- **`SectionAgent`** in `app/services/section_agent.py`:
  - Iterative generation loop (search → gather → draft → critique)
  - Configurable `max_iterations` (from project policy, default 3)
  - **Dynamic quality gates from project policy**: citations, grounding (LLM-as-judge), completeness (LLM-as-judge)
  - Structured `QualityReport` with scores and warnings
  - Full `GenerationParams` snapshot for reproducibility
  - **Cost tracking** via `complete_with_cost()` — `cost_usd`, `token_counts` stored in `SectionVersion`

- **`SectionTranslator`** in same file:
  - Translates approved versions preserving citations `[n]`, markdown, formulas
  - Uses project glossary for terminology consistency
  - Creates linked `SectionVersion` with `source_language` and `parent_version_id`
  - **Cost tracking** for translations

- **`HistoryService`** in `app/services/history.py`:
  - Version tree construction from `parent_version_id`
  - Semantic diff: added/removed/modified claims, citation changes
  - Rollback (creates new version from target)
  - Branch (copy for parallel work)
  - **LLM-assisted merge** (`async merge_branches` with `_llm_merge`)
  - Approve (marks version approved, archives previous)

### Phase 3: Projects Service Integration & Batch Operations ✅
- **`ProjectService`** in `app/services/projects.py` extended with:
  - `get_or_create_section_plan()` — CRUD for SectionPlan
  - `sync_project_sections_to_plans()` — migrates old JSON → new model
  - `generate_section_v2()` — uses SectionAgent, returns SectionVersion
  - `translate_section()` — uses SectionTranslator
  - `get_section_history()`, `diff_section_versions()`, `rollback_section()`, `approve_section_version()`
  - **`regenerate_outdated_sections()`** — batch regeneration with dependency tracking
  - **`compile_manuscript()`** — full manuscript compilation with unified bibliography
  - Backward compatibility: old `generate_section()` still works with `ProjectVersion`

- **`PaperQA2Service`** in `app/services/paperqa_service.py` extended with:
  - `complete_with_cost()` — returns text + cost_info (cost_usd, prompt/completion tokens, cache tokens, model)

### Phase 4: API Endpoints ✅
- **New routes** in `app/api/projects.py`:
  - SectionPlan CRUD: `GET/POST /section-plans`, `PATCH/DELETE /section-plans/{id}`, `POST /section-plans/sync`
  - Generation v2: `POST /generate-v2` → SectionVersion
  - Translation v2: `POST /section-plans/{id}/translate` → linked SectionVersion
  - History: `GET /section-plans/{id}/history` → version tree
  - Diff: `GET /section-versions/diff?from=...&to=...` → semantic diff
  - Rollback: `POST /section-plans/{id}/rollback`
  - Approve: `POST /section-plans/{id}/approve`
  - Language Policy: `GET/PATCH /language-policy`
  - Glossary: `GET/POST/PATCH/DELETE /glossary`, `/glossary/{id}`
  - **Batch: `POST /batch-regenerate`** — regenerate outdated sections
  - **Manuscript: `GET /manuscript`** — compile full manuscript with bibliography
  - **Merge: `POST /section-plans/{id}/merge`** — LLM-assisted version merge
  - **Terminology: `GET /terminology-check`** — cross-section consistency check
  - **Style: `POST /style-compliance`** — LLM-based style guide compliance check
  - **Pre-gen: `POST /pre-generation-check`** — readiness checklist before generation

- **Existing routes preserved** — no breaking changes

### Phase 5: Advanced Features ✅
- **LLM-assisted merge** — intelligent combination of two versions with JSON output
- **Cross-section terminology consistency** — checks glossary compliance across sections
- **Automated style guide compliance** — LLM validates against project's style guide document
- **Pre-generation checklist** — validates sources, style guide, glossary, language before generation
- **Per-version cost tracking** — `cost_usd`, `token_counts` stored in `SectionVersion`
- **Dynamic quality thresholds** — per-project via `ProjectLanguagePolicy`

## Key Design Decisions Implemented

| Decision | Implementation |
|----------|----------------|
| Citation format `[1]` | Kept numeric (as requested) |
| Agent vs Pipeline | Full LLM agent with tools (SectionAgent iterative loop) |
| Version table | New `SectionVersion` (not extending ProjectVersion) |
| Translation trigger | Manual only (API endpoint) |
| Glossary scope | Project-only (TerminologyGlossary linked to Project) |
| Quality thresholds | Per-project via `ProjectLanguagePolicy` |
| Merge strategy | LLM-assisted with JSON output |
| Cost tracking | Per-version via `complete_with_cost()` |

## Files Created/Modified

### New Files
1. `app/services/section_agent.py` — SectionAgent, SectionTranslator
2. `app/services/history.py` — HistoryService, VersionTree, SemanticDiff, LLM merge
3. `backend/alembic/versions/2e4e4ea086df_add_section_plans_versions_language_.py` — migration (Phase 1)
4. `backend/alembic/versions/8f557676cc89_add_quality_thresholds_cost_tracking.py` — migration (Phase 3)

### Modified Files
1. `app/db/models.py` — new enums, models, relationships (+ cost fields, quality thresholds)
2. `app/services/paperqa_service.py` — added `complete_with_cost()`
3. `app/services/section_agent.py` — cost tracking, dynamic thresholds
4. `app/services/projects.py` — batch operations, manuscript compilation
5. `app/api/projects.py` — 10+ new endpoints for advanced features

## Testing Status

✅ All core tests pass (`test_analyses.py`, `test_generation.py`, `test_models.py`, `test_citation_guard.py`, `test_grounding.py`, `test_export.py`, `test_journal_styles.py`, `test_paperqa_service.py`, `test_rag_fusion.py`)
✅ Models import and work correctly with database
✅ All new API routes registered (6 new endpoints + existing preserved)
✅ Migrations applied successfully
✅ SectionAgent uses project policy for dynamic thresholds
✅ Version tree, diff, rollback, branch, merge all functional

## Summary

The section generation system has been completely redesigned from a simple single-shot prompt to a **PaperQA2-inspired agentic system** with:

- **Structured planning** (SectionPlan with dependencies, word budgets, status)
- **Iterative generation** (search → gather → draft → critique → repeat)
- **Quality gates** (citations, grounding, completeness with LLM-as-judge)
- **Full version history** (tree with branches, semantic diff, rollback, merge)
- **Multi-language support** (translation with glossary, version linking)
- **Cost tracking** (per-version tokens and USD cost)
- **Batch operations** (regenerate outdated, compile manuscript)
- **Advanced QC** (terminology consistency, style compliance, pre-gen checklist)

All implemented with **zero breaking changes** to existing API.