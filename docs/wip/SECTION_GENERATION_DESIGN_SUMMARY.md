# Section Generation Redesign — Executive Summary

## Problem
Current section generation is a **single-shot prompt** with basic citation validation. It lacks:
- Iterative evidence gathering (PaperQA2 style)
- Structured section planning with dependencies
- Semantic version history (rollback, diff, branches)
- Integrated translation workflow
- Quality gates beyond citation checking

## Solution: PaperQA2-Inspired Agentic Generator

### Core Changes

| Component | Current | New |
|-----------|---------|-----|
| **Planning** | `Project.sections` JSON | `SectionPlan` table (deps, word budgets, language, status) |
| **Generation** | `build_prompt()` → LLM → validate | `SectionAgent`: search → gather → draft → critique → (repeat) |
| **Versioning** | Linear `ProjectVersion` | Version tree (`SectionVersion`) with branches, semantic diff |
| **Translation** | Ad-hoc `translate_text()` | First-class: version linking, glossary preservation, language tabs |
| **Quality** | Citation check only | Grounding, completeness, style, terminology gates |

### SectionAgent Loop (3 iterations max)

```
Iteration 1:  search_evidence() → gather_summaries() → generate_draft() → critique()
Iteration 2:  (if critique fails) re-search with critique feedback → ... → critique()
Iteration 3:  final attempt → return best with warnings
```

### Translation Workflow

1. Generate in primary language (e.g., Russian)
2. Human approves → `status = APPROVED`
3. Click "Translate" → creates linked `SectionVersion` with `source_language=ru`, `language=en`
4. Preserves: citations `[n]`, markdown, formulas, proper nouns
5. Uses project terminology glossary

### Data Model Additions

```sql
SectionPlan          -- replaces Project.sections JSON
SectionVersion       -- extends ProjectVersion with language, parent_version_id, quality_report
ProjectLanguagePolicy -- primary/allowed languages, auto-translate settings
TerminologyGlossary  -- term → {ru: ..., en: ...} per project
```

### Migration Path (Non-breaking)

1. **Phase 1**: Add new tables, migrate existing data (dual-write)
2. **Phase 2**: `SectionAgent` service + structured prompts
3. **Phase 3**: Translation layer + API endpoints
4. **Phase 4**: History UI (tree, diff, rollback)
5. **Phase 5**: Quality gates + polish

---

## Key Decision Points (Need Your Input)

1. **Citation format**: Keep `[1]` numeric (current) vs. PaperQA2's `(pqac-key)`?
   - *Lean: Keep `[1]` — human-readable, LaTeX-compatible*

2. **Agent vs. Pipeline**: Full LLM agent (tools) vs. structured pipeline (fixed steps)?
   - *Lean: Structured pipeline with LLM critique — predictable, debuggable*

3. **Version table**: Extend `ProjectVersion` vs. new `SectionVersion`?
   - *Lean: New `SectionVersion` — cleaner separation*

4. **Translation trigger**: Manual only vs. auto-on-approve?
   - *Lean: Manual + batch "Translate all approved"*

5. **Glossary scope**: Project-only vs. project + domain presets?
   - *Lean: Project-only with import from domain presets*

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `app/db/models.py` | +SectionPlan, +SectionVersion, +ProjectLanguagePolicy, +TerminologyGlossary |
| `app/services/section_agent.py` | **NEW** — iterative generation |
| `app/services/section_prompts.py` | **NEW** — JSON summary, critique prompts |
| `app/services/translation.py` | **NEW** — translation workflow |
| `app/services/history.py` | **NEW** — version tree, diff, rollback |
| `app/services/projects.py` | Refactor to use SectionAgent |
| `app/api/projects.py` | New endpoints: sections, versions, translate, diff |
| `alembic/versions/...` | Migrations |

---

**Ready for review.** Give go-ahead to start Phase 1 (data model + migrations).