"""Сервис истории версий разделов: дерево версий, семантический diff, rollback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    SectionPlan,
    SectionVersion,
    User,
    VersionStatus,
)
from app.services.generation import validate_citations
from app.services.pqa_registry import get_registry

log = logging.getLogger("boasi.services.history")


# --------------------------------------------------------------------------- dataclasses
@dataclass
class VersionNode:
    """Узел дерева версий."""

    version: SectionVersion
    children: list["VersionNode"] = None  # type: ignore

    def __post_init__(self):
        if self.children is None:
            self.children = []


@dataclass
class SemanticDiff:
    """Семантическая разница между двумя версиями."""

    from_version_id: str
    to_version_id: str
    added_claims: list[dict[str, Any]]
    removed_claims: list[dict[str, Any]]
    modified_claims: list[dict[str, Any]]
    citation_changes: dict[str, Any]
    terminology_changes: dict[str, str]
    word_count_delta: int
    summary: str


@dataclass
class VersionTree:
    """Дерево версий раздела."""

    section_plan_id: str
    section_name: str
    roots: list[VersionNode]
    all_versions: list[SectionVersion]


# --------------------------------------------------------------------------- HistoryService
class HistoryService:
    """Управление историей версий разделов."""

    def __init__(self, db: Session, registry=None) -> None:
        self.db = db
        self.registry = registry or get_registry()

    # ------------------------------------------------------------------ tree
    def get_version_tree(self, section_plan_id: str) -> VersionTree:
        """Получить полное дерево версий раздела."""
        section_plan = self.db.get(SectionPlan, section_plan_id)
        if not section_plan:
            raise ValueError(f"SectionPlan {section_plan_id} not found")

        versions = self.db.execute(
            select(SectionVersion)
            .where(SectionVersion.section_plan_id == section_plan_id)
            .order_by(SectionVersion.created_at)
        ).scalars().all()

        # Построение дерева через parent_version_id
        nodes: dict[str, VersionNode] = {}
        roots: list[VersionNode] = []

        for v in versions:
            nodes[v.id] = VersionNode(version=v)

        for v in versions:
            node = nodes[v.id]
            if v.parent_version_id and v.parent_version_id in nodes:
                nodes[v.parent_version_id].children.append(node)
            else:
                roots.append(node)

        return VersionTree(
            section_plan_id=section_plan_id,
            section_name=section_plan.name,
            roots=roots,
            all_versions=versions,
        )

    def get_version(self, version_id: str) -> SectionVersion | None:
        """Получить версию по ID."""
        return self.db.get(SectionVersion, version_id)

    def get_current_version(self, section_plan_id: str) -> SectionVersion | None:
        """Текущая (последняя) версия раздела."""
        section_plan = self.db.get(SectionPlan, section_plan_id)
        if not section_plan or not section_plan.current_version_id:
            return None
        return self.db.get(SectionVersion, section_plan.current_version_id)

    # ------------------------------------------------------------------ diff
    def diff_versions(self, from_id: str, to_id: str) -> SemanticDiff:
        """Семантический diff между двумя версиями."""
        from_ver = self.get_version(from_id)
        to_ver = self.get_version(to_id)

        if not from_ver or not to_ver:
            raise ValueError("One or both versions not found")

        # Простой текстовый diff + анализ цитат
        from_content = from_ver.content_md or ""
        to_content = to_ver.content_md or ""

        # Извлечение утверждений (claims) из текста
        from_claims = self._extract_claims(from_content)
        to_claims = self._extract_claims(to_content)

        # Сравнение
        added = [c for c in to_claims if c not in from_claims]
        removed = [c for c in from_claims if c not in to_claims]
        modified = self._find_modified(from_claims, to_claims)

        # Изменения в цитатах
        from_cites = set(self._extract_citations(from_content))
        to_cites = set(self._extract_citations(to_content))
        citation_changes = {
            "added": list(to_cites - from_cites),
            "removed": list(from_cites - to_cites),
        }

        # Изменения терминологии (упрощённо)
        terminology_changes = {}

        word_count_delta = to_ver.word_count - from_ver.word_count

        summary = self._generate_diff_summary(added, removed, modified, citation_changes, word_count_delta)

        return SemanticDiff(
            from_version_id=from_id,
            to_version_id=to_id,
            added_claims=added,
            removed_claims=removed,
            modified_claims=modified,
            citation_changes=citation_changes,
            terminology_changes=terminology_changes,
            word_count_delta=word_count_delta,
            summary=summary,
        )

    def _extract_claims(self, text: str) -> list[dict[str, Any]]:
        """Извлечь утверждения (предложения с цитатами) из текста."""
        import re
        claims = []
        # Разбиваем на предложения, ищем те с цитатами
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for i, sent in enumerate(sentences):
            citations = self._extract_citations(sent)
            if citations:
                claims.append({
                    "index": i,
                    "text": sent.strip(),
                    "citations": citations,
                })
        return claims

    def _extract_citations(self, text: str) -> list[int]:
        """Извлечь номера цитат из текста."""
        import re
        found = set()
        for match in re.finditer(r"\[(\d+(?:\s*[,\-–]\s*\d+)*)\]", text):
            group = match.group(1)
            for part in re.split(r"[,]", group):
                part = part.strip()
                span = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", part)
                if span:
                    start, end = int(span.group(1)), int(span.group(2))
                    found.update(range(start, end + 1))
                elif part.isdigit():
                    found.add(int(part))
        return sorted(found)

    def _find_modified(
        self,
        from_claims: list[dict[str, Any]],
        to_claims: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Найти измененные утверждения (похожий текст, разные цитаты)."""
        modified = []
        for fc in from_claims:
            for tc in to_claims:
                if self._similar_text(fc["text"], tc["text"]) and fc["citations"] != tc["citations"]:
                    modified.append({
                        "from": fc,
                        "to": tc,
                        "type": "citation_change",
                    })
        return modified

    def _similar_text(self, a: str, b: str, threshold: float = 0.7) -> bool:
        """Простое сравнение текстов (Jaccard по словам)."""
        if not a or not b:
            return False
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return False
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union) >= threshold

    def _generate_diff_summary(
        self,
        added: list[dict],
        removed: list[dict],
        modified: list[dict],
        citation_changes: dict[str, list[int]],
        word_delta: int,
    ) -> str:
        parts = []
        if added:
            parts.append(f"+{len(added)} новых утверждений")
        if removed:
            parts.append(f"-{len(removed)} удаленных утверждений")
        if modified:
            parts.append(f"~{len(modified)} измененных утверждений")
        if citation_changes["added"]:
            parts.append(f"+цитаты: {citation_changes['added']}")
        if citation_changes["removed"]:
            parts.append(f"-цитаты: {citation_changes['removed']}")
        if word_delta != 0:
            sign = "+" if word_delta > 0 else ""
            parts.append(f"{sign}{word_delta} слов")
        return "; ".join(parts) if parts else "без изменений"

    # ------------------------------------------------------------------ rollback / branch / merge
    def rollback(
        self,
        section_plan_id: str,
        version_id: str,
        user: User,
    ) -> SectionVersion:
        """Откатить раздел к указанной версии (создает новую версию-копию)."""
        target = self.get_version(version_id)
        if not target:
            raise ValueError(f"Version {version_id} not found")

        section_plan = self.db.get(SectionPlan, section_plan_id)
        if not section_plan:
            raise ValueError(f"SectionPlan {section_plan_id} not found")

        # Создаем новую версию на базе целевой
        new_version = SectionVersion(
            id=SectionVersion.__table__.columns["id"].default.arg(),
            section_plan_id=section_plan.id,
            project_id=target.project_id,
            session_id=target.session_id,
            content_md=target.content_md,
            language=target.language,
            source_language=target.source_language,
            word_count=target.word_count,
            citation_map=target.citation_map,
            generation_params={
                **target.generation_params,
                "rollback_from": version_id,
                "rollback_type": "manual",
            },
            seconds=0.0,
            quality_report=target.quality_report,
            status=VersionStatus.draft,
            parent_version_id=target.id,
            created_by=user.id,
        )
        self.db.add(new_version)

        # Обновляем план
        section_plan.current_version_id = new_version.id
        section_plan.status = SectionStatus.review

        self.db.commit()
        return new_version

    def create_branch(
        self,
        section_plan_id: str,
        base_version_id: str,
        user: User,
        branch_name: str | None = None,
    ) -> SectionVersion:
        """Создать ветку от указанной версии (копия для параллельной работы)."""
        base = self.get_version(base_version_id)
        if not base:
            raise ValueError(f"Version {base_version_id} not found")

        section_plan = self.db.get(SectionPlan, section_plan_id)
        if not section_plan:
            raise ValueError(f"SectionPlan {section_plan_id} not found")

        new_version = SectionVersion(
            id=SectionVersion.__table__.columns["id"].default.arg(),
            section_plan_id=section_plan.id,
            project_id=base.project_id,
            session_id=base.session_id,
            content_md=base.content_md,
            language=base.language,
            source_language=base.source_language,
            word_count=base.word_count,
            citation_map=base.citation_map,
            generation_params={
                **base.generation_params,
                "branch_from": base_version_id,
                "branch_name": branch_name or f"branch-{base_version_id[:8]}",
            },
            seconds=0.0,
            quality_report=base.quality_report,
            status=VersionStatus.draft,
            parent_version_id=base.id,
            created_by=user.id,
        )
        self.db.add(new_version)

        section_plan.current_version_id = new_version.id
        section_plan.status = SectionStatus.in_progress

        self.db.commit()
        return new_version

    async def merge_branches(
        self,
        section_plan_id: str,
        target_version_id: str,
        source_version_id: str,
        user: User,
        strategy: str = "llm",
    ) -> SectionVersion:
        """Объединить две ветки (target <- source) с LLM-ассистированием."""
        target = self.get_version(target_version_id)
        source = self.get_version(source_version_id)

        if not target or not source:
            raise ValueError("Target or source version not found")

        if target.section_plan_id != source.section_plan_id:
            raise ValueError("Versions belong to different sections")

        section_plan = self.db.get(SectionPlan, section_plan_id)
        if not section_plan:
            raise ValueError(f"SectionPlan {section_plan_id} not found")

        if strategy == "llm":
            merged_content, merged_citations = await self._llm_merge(
                target, source, section_plan
            )
        else:
            merged_content = self._simple_merge(target.content_md, source.content_md)
            merged_citations = self._merge_citations(target.citation_map, source.citation_map)

        new_version = SectionVersion(
            id=SectionVersion.__table__.columns["id"].default.arg(),
            section_plan_id=section_plan.id,
            project_id=target.project_id,
            session_id=target.session_id,
            content_md=merged_content,
            language=target.language,
            source_language=target.source_language,
            word_count=len(merged_content.split()),
            citation_map=merged_citations,
            generation_params={
                "merged_from": [target_version_id, source_version_id],
                "merge_strategy": strategy,
            },
            seconds=0.0,
            quality_report={},
            status=VersionStatus.draft,
            parent_version_id=target.id,
            created_by=user.id,
        )
        self.db.add(new_version)

        section_plan.current_version_id = new_version.id
        section_plan.status = SectionStatus.review

        self.db.commit()
        return new_version

    async def _llm_merge(
        self,
        target: SectionVersion,
        source: SectionVersion,
        section_plan: SectionPlan,
    ) -> tuple[str, list[dict]]:
        """LLM-ассистированное слияние двух версий."""
        # Подготавливаем контекст для LLM
        prompt = f"""Слей две версии одного раздела научной статьи в одну лучшую версию.

ВЕРСИЯ А (базовая):
{target.content_md[:3000]}

ЦИТАТЫ ВЕРСИИ А:
{target.citation_map}

ВЕРСИЯ Б (вливаемая):
{source.content_md[:3000]}

ЦИТАТЫ ВЕРСИИ Б:
{source.citation_map}

ЗАДАЧА:
1. Сохрани всё лучшее из обеих версий
2. Устрани противоречия (факт в версии Б приоритетнее, если он новее/точнее)
3. Объедини списки литературы без дублей
4. Сохрани номера цитат [n] из обеих версий, но перенумеруй итоговый список
5. Верни результат ТОЛЬКО в формате JSON:
{{
  "content_md": "...",
  "citation_map": [
    {{"index": 1, "title": "...", "dockey": "...", "citation": "..."}},
    ...
  ]
}}

НЕ ДОБАВЛЯЙ НИКАКОГО ЛИШНЕГО ТЕКСТА, ТОЛЬКО JSON.
"""
        try:
            service = self.registry.global_service()
            result = await service.complete(prompt, name="merge_branches")
            import json
            data = json.loads(result)
            content = data.get("content_md", target.content_md)
            citations = data.get("citation_map", [])
            # Дополняем citations недостающими полями
            return content, citations
        except Exception as e:
            log.warning(f"LLM merge failed, falling back to simple: {e}")
            return self._simple_merge(target.content_md, source.content_md), \
                   self._merge_citations(target.citation_map, source.citation_map)

    def _simple_merge(self, target: str, source: str) -> str:
        """Простое слияние: target + уникальные абзацы из source."""
        # Упрощенно: возвращаем target, в реальности нужен LLM-merge
        return target

    def _merge_citations(self, target: list[dict], source: list[dict]) -> list[dict]:
        """Объединить карты цитат без дублей."""
        seen = set()
        merged = []
        for c in target + source:
            idx = c.get("index")
            if idx not in seen:
                seen.add(idx)
                merged.append(c)
        return merged

    # ------------------------------------------------------------------ approval
    def approve_version(
        self,
        section_plan_id: str,
        version_id: str,
        user: User,
    ) -> SectionVersion:
        """Одобрить версию (перевод в статус approved)."""
        version = self.get_version(version_id)
        if not version:
            raise ValueError(f"Version {version_id} not found")

        section_plan = self.db.get(SectionPlan, section_plan_id)
        if not section_plan:
            raise ValueError(f"SectionPlan {section_plan_id} not found")

        # Деактивируем старую approved версию
        if section_plan.current_version_id and section_plan.current_version_id != version_id:
            old = self.db.get(SectionVersion, section_plan.current_version_id)
            if old and old.status == VersionStatus.approved:
                old.status = VersionStatus.archived

        version.status = VersionStatus.approved
        section_plan.current_version_id = version.id
        section_plan.status = SectionStatus.approved

        self.db.commit()
        return version