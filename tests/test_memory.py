"""
Tests for the 3-layer evolutionary memory system.
"""

import pytest
from mutagen.memory import MemoryManager
from mutagen.schemas import MemoryRecord, MemoryType


def test_memory_layers_storage_and_retrieval(db_session):
    mgr = MemoryManager(db_session)

    # Add project constraint
    mgr.store_project_memory(
        project_id="proj_1",
        content="Must maintain strict typing with annotations",
        tags=["typing", "high_priority"],
    )

    # Add evolution lesson
    mgr.store_evolution_memory(
        project_id="proj_1",
        experiment_id="exp_1",
        content="Recursion depth limit exceeded on large N inputs",
        tags=["recursion", "failure"],
    )

    # Add semantic pattern
    mgr.store_semantic_memory(
        content="Memoization using functools.lru_cache reduces exponential to linear time",
        tags=["caching", "python"],
    )

    # Retrieve context
    context = mgr.retrieve_context(project_id="proj_1", language="python")

    assert context is not None
    assert len(context.project_memories) >= 1
    assert "strict typing" in context.project_memories[0].content

    assert len(context.evolution_memories) >= 1
    assert "Recursion depth" in context.evolution_memories[0].content

    assert len(context.semantic_memories) >= 1
    assert "Memoization" in context.semantic_memories[0].content
