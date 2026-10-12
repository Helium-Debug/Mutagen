"""
Evolutionary memory system for MUTAGEN.

Implements three memory layers:
1. Project Memory — structure, interfaces, constraints
2. Evolution Memory — mutation attempts, results, lessons
3. Semantic Memory — searchable patterns and strategies

Uses PostgreSQL as the storage backend with text-based retrieval
(no paid embeddings required).
"""

from __future__ import annotations

from typing import Optional

from mutagen.core.identifiers import generate_id
from mutagen.core.logging import get_logger
from mutagen.schemas import MemoryContext, MemoryRecord, MemoryType

logger = get_logger("memory")


class MemoryManager:
    """
    Manages all three memory layers.

    Provides relevant memory retrieval for mutation generation
    and stores experiment outcomes for future reference.
    """

    def __init__(self, session, user_id: Optional[str] = None):
        from mutagen.db.repositories import MemoryRepository
        self.repo = MemoryRepository(session)
        self.session = session
        self.user_id = user_id

    def store_project_memory(
        self,
        project_id: str,
        content: str,
        language: str = "python",
        tags: Optional[list[str]] = None,
        relevance: float = 1.0,
        user_id: Optional[str] = None,
    ) -> MemoryRecord:
        """Store a project memory record."""
        record = self.repo.create(
            user_id=user_id or self.user_id,
            memory_type=MemoryType.PROJECT.value,
            project_id=project_id,
            language=language,
            content=content,
            tags={"tags": tags or []},
            relevance_score=relevance,
        )
        logger.debug(f"Stored project memory: {record.id}")
        return self._to_schema(record)

    def store_evolution_memory(
        self,
        content: str,
        project_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
        language: str = "python",
        tags: Optional[list[str]] = None,
        relevance: float = 1.0,
        user_id: Optional[str] = None,
    ) -> MemoryRecord:
        """Store an evolution memory record (mutation attempt results)."""
        record = self.repo.create(
            user_id=user_id or self.user_id,
            memory_type=MemoryType.EVOLUTION.value,
            project_id=project_id,
            experiment_id=experiment_id,
            language=language,
            content=content,
            tags={"tags": tags or []},
            relevance_score=relevance,
        )
        logger.debug(f"Stored evolution memory: {record.id}")
        return self._to_schema(record)

    def store_semantic_memory(
        self,
        content: str,
        project_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
        language: str = "python",
        tags: Optional[list[str]] = None,
        relevance: float = 1.0,
        user_id: Optional[str] = None,
    ) -> MemoryRecord:
        """Store a semantic memory record (reusable patterns)."""
        record = self.repo.create(
            user_id=user_id or self.user_id,
            memory_type=MemoryType.SEMANTIC.value,
            project_id=project_id,
            experiment_id=experiment_id,
            language=language,
            content=content,
            tags={"tags": tags or []},
            relevance_score=relevance,
        )
        logger.debug(f"Stored semantic memory: {record.id}")
        return self._to_schema(record)

    def retrieve_context(
        self,
        project_id: Optional[str] = None,
        language: str = "python",
        limit: int = 10,
        user_id: Optional[str] = None,
    ) -> MemoryContext:
        """
        Retrieve relevant memory context for mutation generation.

        Queries all three memory layers and returns bounded results.
        """
        uid = user_id or self.user_id
        project_memories = []
        evolution_memories = []
        semantic_memories = []

        if project_id:
            raw_project = self.repo.search(
                memory_type=MemoryType.PROJECT.value,
                project_id=project_id,
                user_id=uid,
                limit=limit,
            )
            project_memories = [self._to_schema(r) for r in raw_project]

        raw_evolution = self.repo.search(
            memory_type=MemoryType.EVOLUTION.value,
            project_id=project_id,
            language=language,
            user_id=uid,
            limit=limit,
        )
        evolution_memories = [self._to_schema(r) for r in raw_evolution]

        raw_semantic = self.repo.search(
            memory_type=MemoryType.SEMANTIC.value,
            language=language,
            user_id=uid,
            limit=limit,
        )
        semantic_memories = [self._to_schema(r) for r in raw_semantic]

        total = len(project_memories) + len(evolution_memories) + len(semantic_memories)

        return MemoryContext(
            project_memories=project_memories,
            evolution_memories=evolution_memories,
            semantic_memories=semantic_memories,
            total_records=total,
        )

    def search_memories(
        self,
        query: str,
        user_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Search memories by content text."""
        uid = user_id or self.user_id
        raw = self.repo.search_by_content(query, user_id=uid, limit=limit)
        return [self._to_schema(r) for r in raw]

    def get_stats(self, user_id: Optional[str] = None) -> dict[str, int]:
        """Get memory statistics by type."""
        uid = user_id or self.user_id
        return self.repo.count_by_type(user_id=uid)


    def store_experiment_outcome(
        self,
        experiment_id: str,
        project_id: Optional[str],
        language: str,
        summary: str,
        strategies_tried: list[str],
        best_improvement: Optional[float],
        failures: list[str],
    ) -> None:
        """
        Store comprehensive experiment outcome in evolution memory.

        Creates both evolution and semantic memory records.
        """
        # Evolution memory: detailed outcome
        evolution_content = (
            f"Experiment {experiment_id}: {summary}\n"
            f"Strategies tried: {', '.join(strategies_tried)}\n"
            f"Best improvement: {best_improvement}%\n"
        )
        if failures:
            evolution_content += f"Failures: {'; '.join(failures[:5])}\n"

        self.store_evolution_memory(
            content=evolution_content,
            project_id=project_id,
            experiment_id=experiment_id,
            language=language,
            tags=strategies_tried,
            relevance=min(1.0, (best_improvement or 0) / 100 + 0.5),
        )

        # Semantic memory: reusable lesson
        if best_improvement and best_improvement > 0:
            lesson = (
                f"Successful optimization pattern: {summary}. "
                f"Achieved {best_improvement:.1f}% improvement "
                f"using strategies: {', '.join(strategies_tried)}."
            )
            self.store_semantic_memory(
                content=lesson,
                project_id=project_id,
                experiment_id=experiment_id,
                language=language,
                tags=["successful_pattern"] + strategies_tried,
                relevance=min(1.0, best_improvement / 50),
            )

    def _to_schema(self, db_record) -> MemoryRecord:
        """Convert a DB MemoryRecord to a schema MemoryRecord."""
        tags = []
        if db_record.tags and isinstance(db_record.tags, dict):
            tags = db_record.tags.get("tags", [])

        return MemoryRecord(
            record_id=db_record.id,
            memory_type=MemoryType(db_record.memory_type),
            project_id=db_record.project_id,
            experiment_id=db_record.experiment_id,
            language=db_record.language,
            content=db_record.content,
            tags=tags,
            relevance_score=db_record.relevance_score,
            created_at=db_record.created_at,
        )
