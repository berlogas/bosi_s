# Section Generation Design: Comparison with PaperQA2 & Improvement Plan

> **Status**: Design phase — code not changed yet. Read and approve before implementation.

---

## 1. Current Architecture (boasi_s)

### 1.1 Core Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `GenerationResult` | `generation.py` | Dataclass holding generated content, citations, validation |
| `build_prompt()` | `generation.py` | Constructs LLM prompt with sources, rules, style |
| `validate_citations()` | `generation.py` | Enforces citation contract: every `[n]` must resolve |
| `ProjectService.generate_section()` | `projects.py` | Orchestrates retrieval → prompt → LLM → validation → versioning |
| `RagFusionService` | `rag_fusion.py` | Hybrid retrieval (global + session + project docs) |
| `PaperQA2Service.complete()` | `paperqa_service.py` | Low-level LLM call (shared model with retrieval) |
| `ProjectVersion` | `models.py` | Immutable snapshot per generation |

### 1.2 Generation Flow

```
User Request
    │
    ▼
ProjectService.generate_section()
    │
    ├─► Cache check (same section + question + language)
    │
    ├─► RagFusionService.retrieve()  ──► sources (with indices 1..N)
    │
    ├─► _build_prompt()  ──► prompt with:
    │       • Section name, question, notes
    │       • Language (project.language)
    │       • Journal style (project.target_journal)
    │       • Style guide document (if attached)
    │       • Sources numbered 1..N
    │       • Hard citation rules
    │
    ├─► PaperQA2Service.complete()  ──► raw text
    │
    ├─► validate_citations(text, N)  ──► CitationCheck
    │
    ├─► build_citation_map()  ──► citation_map for UI
    │
    └─► _save_version()  ──► ProjectVersion + update Project.sections
```

### 1.3 Strengths

- **Citation contract enforced** — `validate_citations()` rejects dangling refs
- **Version history** — every generation saved as `ProjectVersion`
- **Multi-kind generation** — section, literature_review, discussion, data_comparison, gap_analysis, report, draft_analysis
- **Language support** — `project.language` + `request.language` override
- **Journal styles** — `journal_styles.style_prompt()` per section
- **Cache** — avoids re-generation for identical (section, question, language)

### 1.4 Weaknesses / Gaps

| Area | Current | Desired |
|------|---------|---------|
| **Generation strategy** | Single-shot prompt | Iterative agentic (search → gather → answer → refine) |
| **Section planning** | Static `DEFAULT_SECTIONS` | Dynamic, paper-type aware, editable plan |
| **Change history** | `ProjectVersion` rows only | Semantic diff, rollback, branch/merge |
| **Translation** | `translate_text()` exists but not integrated | One-click translate any version to project language |
| **Cross-section consistency** | None | Shared terminology, reference list, outline awareness |
| **Quality gates** | Citation check only | Grounding, completeness, style compliance |
| **Human-in-the-loop** | Generate → done | Review → regenerate section → accept |

---

## 2. PaperQA2 (WikiCrow) Approach

### 2.1 Key Insights from `wikicrow.json` & Agent Tools

| Aspect | PaperQA2 Design |
|--------|-----------------|
| **Workflow** | Agentic loop: `paper_search` → `gather_evidence` → `gen_answer` → `complete` |
| **Iteration** | Agent decides when evidence is sufficient; can re-search, re-gather |
| **Prompts** | JSON-structured summaries (`summary_json_system_prompt`) |
| **Citation format** | Strict: `(pqac-1234abcd)` keys, no free-form `[1]` |
| **Answer style** | "Wikipedia article: concise sentences, coherent paragraphs" |
| **System prompt** | "Direct and concise tone. Expert audience. Define ambiguous terms." |
| **Evidence target** | 25 chunks retrieved, 12 max sources in answer |
| **Summary length** | ~300 words per evidence chunk |
| **Temperature** | 0.0 (deterministic) |

### 2.2 What PaperQA2 Does NOT Have

- Project/section planning (it answers single questions)
- Version history / change tracking
- Multi-section document generation
- Translation workflow
- Journal-specific style guides
- Human review gates

### 2.3 Transferable Patterns

1. **Iterative evidence gathering** — don't assume first retrieval is enough
2. **Structured summary prompts** — JSON output for reliable parsing
3. **Explicit "cannot answer" sentinel** — `I cannot answer` phrase
4. **Agent-driven tool selection** — LLM decides next action
5. **Evidence quality thresholds** — minimum sources before answering

---

## 3. Proposed Design: "PaperQA2-Inspired Section Generator"

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    SectionGenerationService                 │
├─────────────────────────────────────────────────────────────┤
│  PlanManager          │  SectionAgent          │  History    │
│  ─────────────────    │  ─────────────────     │  ─────────  │
│  • Outline CRUD       │  • Iterative loop      │  • Version  │
│  • Section deps       │  • Tool: search        │    tree     │
│  • Word budgets       │  • Tool: gather        │  • Semantic │
│  • Language policy    │  • Tool: answer        │    diff     │
│  • Journal profile    │  • Tool: critique      │  • Rollback │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  TranslationLayer │
                    │  ──────────────── │
                    │  • Translate any  │
                    │    version        │
                    │  • Preserve cites │
                    │  • Term glossary  │
                    └───────────────────┘
```

### 3.2 Core Entities (New / Extended)

#### `SectionPlan` (replaces `Project.sections` JSON)

```python
@dataclass
class SectionPlan:
    id: str                    # UUID
    project_id: str
    name: str                  # "Introduction", "Methods", etc.
    order: int
    kind: SectionKind          # STANDARD | LITERATURE_REVIEW | DATA | DISCUSSION | CUSTOM
    required: bool
    word_target: int
    word_min: int
    word_max: int
    notes: str                 # Author guidance
    language: str              # Target language (ru/en/...)
    depends_on: list[str]      # Section IDs that must be done first
    status: SectionStatus      # PENDING | IN_PROGRESS | REVIEW | APPROVED
    current_version_id: str | None
    created_at: datetime
    updated_at: datetime
```

#### `SectionVersion` (extends `ProjectVersion`)

```python
@dataclass
class SectionVersion:
    id: str
    section_plan_id: str
    content_md: str
    language: str              # Language THIS version is written in
    source_language: str | None  # If translated, original language
    citation_map: list[CitationRef]
    word_count: int
    generation_params: GenerationParams  # Full reproducibility
    quality_checks: QualityReport
    parent_version_id: str | None      # For translations/edits
    created_by: str
    created_at: datetime
    status: VersionStatus    # DRAFT | REVIEW | APPROVED | SUPERSEDED
```

#### `GenerationParams` (immutable snapshot)

```python
@dataclass
class GenerationParams:
    question: str
    notes: str
    style_guide_text: str | None
    journal_style: str | None
    sources_used: list[SourceRef]  # dockey, index, citation
    retrieval_mode: SearchMode
    evidence_k: int
    max_sources: int
    temperature: float
    model: str
    prompt_template_version: str
```

#### `QualityReport`

```python
@dataclass
class QualityReport:
    citations_ok: bool
    dangling_citations: list[int]
    unused_sources: list[int]
    grounding_score: float | None      # 0-1, LLM-judged
    completeness_score: float | None   # 0-1, covers all question aspects
    style_compliance: dict[str, bool]  # journal rules
    terminology_consistency: dict[str, str]  # term → canonical form
    warnings: list[str]
```

### 3.3 SectionAgent: Iterative Generation Loop

```python
class SectionAgent:
    """PaperQA2-style agent for single-section generation."""
    
    async def generate(
        self,
        section: SectionPlan,
        project: Project,
        session: ResearchSession,
        params: GenerationParams,
        *,
        max_iterations: int = 3,
    ) -> SectionVersion:
        
        iteration = 0
        current_draft = None
        evidence = []
        
        while iteration < max_iterations:
            iteration += 1
            
            # 1. SEARCH (if first iteration or needs more)
            if iteration == 1 or self._needs_more_evidence(evidence, params):
                new_sources = await self._search_evidence(
                    section, project, session, params, evidence
                )
                evidence.extend(new_sources)
            
            # 2. GATHER — summarize evidence for this section
            summaries = await self._gather_summaries(
                section, evidence, params
            )
            
            # 3. ANSWER — generate draft
            draft = await self._generate_draft(
                section, summaries, params, previous_draft=current_draft
            )
            
            # 4. CRITIQUE — self-evaluation
            critique = await self._critique_draft(
                section, draft, evidence, params
            )
            
            if critique.passes_quality_gate():
                return self._finalize_version(draft, evidence, params, critique)
            
            current_draft = draft
            # Loop continues with critique feedback as additional guidance
        
        # Max iterations reached — return best with warnings
        return self._finalize_version(current_draft, evidence, params, critique)
```

**Tools available to agent:**

| Tool | Purpose |
|------|---------|
| `search_evidence` | Query global/session/project indexes with section-specific query |
| `gather_summaries` | Summarize each evidence chunk for the section question |
| `generate_draft` | Write section with citations, using journal style |
| `critique_draft` | Check citations, grounding, completeness, style |
| `translate_section` | Translate approved version to another language |

### 3.4 Language & Translation Design

#### Language Policy

```python
@dataclass
class ProjectLanguagePolicy:
    primary_language: str           # Project default (from project.language)
    allowed_languages: list[str]    # ["ru", "en"]
    translate_on_approve: bool      # Auto-translate approved sections?
    terminology_glossary: dict[str, dict[str, str]]  # term → {ru: ..., en: ...}
```

#### Translation Workflow

1. **Generate in primary language** (e.g., Russian)
2. **Human approves** → status = `APPROVED`
3. **One-click translate** to any allowed language:
   - Calls `PaperQA2Service.translate_text()` with strict prompt
   - Preserves: citations `[n]`, markdown, formulas, proper nouns
   - Creates new `SectionVersion` with `source_language=primary`, `language=target`
   - Links via `parent_version_id`
4. **Both versions coexist** — UI shows language tabs

#### Translation Prompt (enhanced from current)

```python
TRANSLATE_SECTION_PROMPT = """
Translate the following scientific article section from {source_lang} to {target_lang}.

STRICT RULES:
1. PRESERVE EXACTLY: citation markers [1], [2,3], [1-3]; markdown structure (headings, lists, tables); 
   mathematical formulas ($...$, $$...$$); proper nouns (geographic names, device names, method names, 
   abbreviations, chemical formulas, gene/protein symbols).
2. TRANSLATE: all natural language text maintaining formal scientific style.
3. TERMINOLOGY: use project glossary if provided; otherwise use standard domain translations.
4. NO CREATIVE ADAPTATION — literal but fluent translation.

GLOSSARY:
{glossary_json}

SECTION:
{content_md}

TRANSLATION:
"""
```

### 3.5 Change History & Versioning

#### Version Tree (not linear list)

```
Section: "Introduction"
│
├─ v1 (ru) ── draft, generated
│   ├─ v1.1 (ru) ── human edit
│   │   └─ v1.1 (en) ── translated from v1.1
│   └─ v2 (ru) ── regenerated with new sources
│       └─ v2 (en) ── translated from v2
└─ v3 (ru) ── merged from v1.1 + v2 edits
    └─ v3 (en) ── translated from v3
```

#### API for History

```python
class SectionHistoryService:
    def get_version_tree(self, section_plan_id: str) -> VersionTree
    def get_version(self, version_id: str) -> SectionVersion
    def diff_versions(self, from_id: str, to_id: str) -> SemanticDiff
    def rollback(self, section_plan_id: str, version_id: str, user: User) -> SectionVersion
    def create_branch(self, section_plan_id: str, base_version_id: str, name: str) -> SectionVersion
    def merge_branches(self, target_id: str, source_id: str, strategy: MergeStrategy) -> SectionVersion
```

#### Semantic Diff (not line-based)

```python
@dataclass
class SemanticDiff:
    added_claims: list[Claim]        # New statements with citations
    removed_claims: list[Claim]
    modified_claims: list[ClaimDiff] # Changed meaning, same citation
    citation_changes: CitationDiff   # Added/removed/changed refs
    terminology_changes: dict[str, str]
    word_count_delta: int
```

### 3.6 Quality Gates (Pre-commit for Versions)

| Gate | Check | Blocking? |
|------|-------|-----------|
| **Citations** | All `[n]` resolve, no dangling, min 1 per paragraph (configurable) | YES |
| **Grounding** | LLM judges: "Is every claim supported by cited sources?" | YES (threshold) |
| **Completeness** | LLM judges: "Does this address the section question/notes?" | WARNING |
| **Style** | Journal rules (passive voice, tense, abbreviation list) | WARNING |
| **Terminology** | Consistent with project glossary & prior sections | WARNING |
| **Length** | Within `word_min`..`word_max` | WARNING |

---

## 4. Migration Plan: Current → Proposed

### Phase 1: Data Model (Non-breaking)
1. Add `SectionPlan` table (parallel to `Project.sections` JSON)
2. Add `SectionVersion` table (extends `ProjectVersion`)
3. Add `ProjectLanguagePolicy` table
4. Add `TerminologyGlossary` table
5. Migrate existing `Project.sections` → `SectionPlan` rows
6. Migrate existing `ProjectVersion` → `SectionVersion` rows

### Phase 2: SectionAgent (New Service)
1. Create `SectionAgent` class with iterative loop
2. Implement tools: `search_evidence`, `gather_summaries`, `generate_draft`, `critique_draft`
3. Add structured prompts (JSON summaries like WikiCrow)
4. Integrate with existing `RagFusionService` and `PaperQA2Service`

### Phase 3: Translation Layer
1. Enhance `translate_text()` with glossary support
2. Add `translate_section()` to `SectionAgent`
3. UI: language tabs per section, "Translate" button on approved versions

### Phase 4: History & Diff
1. Implement `SectionHistoryService`
2. Semantic diff engine (LLM-assisted)
3. Rollback / branch / merge APIs
4. UI: version timeline, diff view, restore button

### Phase 5: Quality Gates & Polish
1. Configurable quality gate thresholds per project/journal
2. Pre-generation checklist UI
3. Batch operations: "Regenerate all outdated sections"
4. Export: compile full manuscript with consistent references

---

## 5. Comparison Summary

| Dimension | Current (boasi_s) | PaperQA2 (WikiCrow) | Proposed |
|-----------|-------------------|---------------------|----------|
| **Generation** | Single-shot | Agentic iterative | Agentic iterative |
| **Evidence** | One retrieval | Search → gather → re-search | Search → gather → critique → re-search |
| **Citations** | `[1]` numeric, validated | `(pqac-key)` keys, strict format | `[1]` numeric, validated + format check |
| **Sections** | Flat JSON plan | N/A (single answer) | Structured `SectionPlan` with deps |
| **Versioning** | Linear `ProjectVersion` | N/A | Version tree with branches |
| **Translation** | Ad-hoc `translate_text()` | N/A | First-class: version linking, glossary |
| **Quality** | Citation check only | Implicit via agent | Explicit gates: grounding, completeness, style |
| **Journal Style** | `journal_styles` + style guide doc | System prompt only | Both + compliance checking |
| **Human Loop** | Generate → done | N/A | Draft → Review → Approve → Translate |

---

## 6. Key Decisions Needed

1. **Citation format**: Keep `[1]` numeric (current) or adopt `(pqac-key)` (PaperQA2)?
   - *Recommendation*: Keep `[1]` — better for human reading, matches LaTeX/Word

2. **Agent vs. deterministic pipeline**: Full LLM agent (tools) or structured pipeline (fixed steps)?
   - *Recommendation*: Structured pipeline with LLM critique step — more predictable, easier to debug

3. **Version storage**: Separate `SectionVersion` table or extend `ProjectVersion`?
   - *Recommendation*: New `SectionVersion` table — cleaner, avoids migration complexity

4. **Translation trigger**: Manual only, or auto-on-approve?
   - *Recommendation*: Manual with "Translate all approved" batch action

5. **Glossary management**: Project-level only, or also global/domain?
   - *Recommendation*: Project-level with import from domain presets

---

## 7. Implementation Priority (MVP)

| Priority | Feature | Effort |
|----------|---------|--------|
| P0 | `SectionPlan` model + migration | M |
| P0 | `SectionVersion` model + migration | M |
| P0 | `SectionAgent` with 3-iteration loop | L |
| P0 | Structured prompts (JSON summaries) | M |
| P1 | Translation workflow (version linking) | M |
| P1 | Quality gates (grounding, completeness) | M |
| P2 | Semantic diff / version tree UI | L |
| P2 | Branch/merge | L |
| P3 | Glossary management UI | M |

---

## 8. Code Mapping: Where Changes Land

| New/Modified File | Purpose |
|-------------------|---------|
| `app/db/models.py` | Add `SectionPlan`, `SectionVersion`, `ProjectLanguagePolicy`, `TerminologyGlossary` |
| `app/services/section_agent.py` | **NEW** — iterative generation agent |
| `app/services/section_prompts.py` | **NEW** — structured prompts (JSON summaries, critique) |
| `app/services/translation.py` | **NEW** — translation workflow, glossary |
| `app/services/history.py` | **NEW** — version tree, diff, rollback |
| `app/services/projects.py` | Refactor: delegate to `SectionAgent`, use `SectionPlan` |
| `app/services/generation.py` | Keep: `validate_citations`, `build_citation_map`, `GenerationResult` |
| `app/api/projects.py` | New endpoints: section CRUD, version history, translate, diff |
| `alembic/versions/...` | Migrations for new tables |

---

## 9. Open Questions for Review

1. **Should we keep `Project.sections` JSON for backward compat?** — Yes, sync both ways initially
2. **How to handle multi-language projects where sections are written in different languages?** — `SectionPlan.language` per section, project default as fallback
3. **Citation renumbering on translation?** — No, keep same `[n]` numbers; citation_map carries source info
4. **Regeneration trigger?** — Manual + "Regenerate if sources changed" checkbox
5. **Cost tracking per section?** — Add to `SectionVersion.stats` (tokens, USD, seconds)

---

*End of design document. Awaiting approval to proceed with implementation.*