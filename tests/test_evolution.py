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


def test_evolution_stagnation_carries_on_without_failing(tmp_path, monkeypatch, mock_sandbox):
    code_file = tmp_path / "fib2.py"
    code_file.write_text(
        "def fib(n: int) -> int:\n    if n <= 1: return n\n    return fib(n-1) + fib(n-2)\n",
        encoding="utf-8"
    )

    monkeypatch.setattr(
        "mutagen.evolution.engine.DockerSandbox",
        lambda: mock_sandbox
    )

    # 3 generations with stop_on_stagnation=False (default)
    config = ExperimentConfig(
        source_file=str(code_file),
        language=ProgrammingLanguage.PYTHON,
        objective=OptimizationObjective.SPEED,
        generations=3,
        population_size=1,
        benchmark_repetitions=1,
        execution_timeout=5,
        stop_on_stagnation=False,
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

    # Must complete all 3 generations without stopping prematurely or failing
    assert summary.status == ExperimentStatus.SUCCEEDED
    assert summary.generations_completed == 3
    assert summary.best_candidate_id is not None


def test_evolution_stagnation_stopped_does_not_fail(tmp_path, monkeypatch, mock_sandbox):
    code_file = tmp_path / "fib3.py"
    code_file.write_text(
        "def fib(n: int) -> int:\n    if n <= 1: return n\n    return fib(n-1) + fib(n-2)\n",
        encoding="utf-8"
    )

    monkeypatch.setattr(
        "mutagen.evolution.engine.DockerSandbox",
        lambda: mock_sandbox
    )

    # 4 generations with stop_on_stagnation=True
    config = ExperimentConfig(
        source_file=str(code_file),
        language=ProgrammingLanguage.PYTHON,
        objective=OptimizationObjective.SPEED,
        generations=4,
        population_size=1,
        benchmark_repetitions=1,
        execution_timeout=5,
        stop_on_stagnation=True,
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

    # Even when stopped early for stagnation, status MUST NOT be FAILED
    assert summary.status == ExperimentStatus.SUCCEEDED
    assert summary.best_candidate_id is not None
