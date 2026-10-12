"""
End-to-end integration tests for the EvolutionEngine.
"""

import pytest
from pathlib import Path

from mutagen.evolution.engine import EvolutionEngine
from mutagen.ai.fake_provider import FakeProvider
from mutagen.schemas import (
    ExperimentConfig, ExperimentStatus, OptimizationObjective,
    ProgrammingLanguage,
)
from mutagen.sandbox.docker_manager import SandboxResult


def test_evolution_engine_end_to_end_loop(tmp_path, monkeypatch, mock_sandbox):
    # Setup test file
    code_file = tmp_path / "fib.py"
    code_file.write_text(
        "def fib(n: int) -> int:\n    if n <= 1: return n\n    return fib(n-1) + fib(n-2)\n",
        encoding="utf-8"
    )

    # Mock DockerSandbox execution inside the engine
    monkeypatch.setattr(
        "mutagen.evolution.engine.DockerSandbox",
        lambda: mock_sandbox
    )

    config = ExperimentConfig(
        source_file=str(code_file),
        language=ProgrammingLanguage.PYTHON,
        objective=OptimizationObjective.SPEED,
        generations=2,
        population_size=2,
        benchmark_repetitions=2,
        execution_timeout=5,
    )

    ai = FakeProvider()
    events = []

    def progress_callback(stage: str, message: str):
        events.append((stage, message))

    engine = EvolutionEngine(
        ai_provider=ai,
        config=config,
        progress_callback=progress_callback,
    )

    summary = engine.run()

    assert summary is not None
    assert summary.status == ExperimentStatus.SUCCEEDED
    assert summary.generations_completed == 2
    assert summary.total_candidates >= 2
    assert summary.valid_candidates >= 1
    assert len(events) > 0
