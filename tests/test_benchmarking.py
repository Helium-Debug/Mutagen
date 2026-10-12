"""
Tests for the benchmarking engine.
"""

import pytest
from mutagen.benchmarking import BenchmarkRunner, compare_benchmarks
from mutagen.sandbox.docker_manager import DockerSandbox, SandboxResult
from mutagen.schemas import BenchmarkResult


def test_benchmark_runner_aggregation(mock_sandbox):
    runner = BenchmarkRunner(
        sandbox=mock_sandbox,
        repetitions=3,
        warmup_runs=1,
        timeout=10,
    )

    result = runner.benchmark(
        candidate_id="cand_test",
        code="x = sum(range(1000))",
    )

    assert result.candidate_id == "cand_test"
    assert result.measured_runs == 3
    assert result.median_time > 0.0
    assert result.mean_time > 0.0


def test_compare_benchmarks():
    baseline = BenchmarkResult(
        candidate_id="baseline",
        median_time=0.10,
        mean_time=0.10,
    )
    candidate = BenchmarkResult(
        candidate_id="fast_cand",
        median_time=0.05,
        mean_time=0.05,
    )

    comparison = compare_benchmarks(baseline, candidate)
    assert comparison["is_faster"] is True
    assert comparison["speed_improvement_percent"] == 50.0
