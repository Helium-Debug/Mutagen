"""
Benchmarking engine for MUTAGEN.

Runs multiple executions, collects timing statistics, and
compares candidate performance against the baseline.

All benchmarks run inside the isolated sandbox.
"""

from __future__ import annotations

import statistics
from typing import Optional

from mutagen.core.logging import get_logger
from mutagen.sandbox.docker_manager import DockerSandbox, SandboxResult
from mutagen.schemas import BenchmarkMeasurement, BenchmarkResult

logger = get_logger("benchmarking")


class BenchmarkRunner:
    """
    Runs repeated benchmark measurements in the sandbox.

    Uses warm-up runs and multiple measured repetitions
    for statistical validity.
    """

    def __init__(
        self,
        sandbox: DockerSandbox,
        repetitions: int = 5,
        warmup_runs: int = 1,
        timeout: int = 30,
    ):
        self.sandbox = sandbox
        self.repetitions = repetitions
        self.warmup_runs = warmup_runs
        self.timeout = timeout

    def benchmark(
        self,
        candidate_id: str,
        code: str,
        benchmark_code: Optional[str] = None,
    ) -> BenchmarkResult:
        """
        Run benchmark measurements for a piece of code.

        Args:
            candidate_id: Identifier for the candidate.
            code: The code to benchmark.
            benchmark_code: Optional additional benchmark harness code.

        Returns:
            BenchmarkResult with aggregated statistics.
        """
        measurements = []

        # Warm-up runs (not measured)
        for i in range(self.warmup_runs):
            logger.debug(f"Warm-up run {i + 1}/{self.warmup_runs} for {candidate_id}")
            self.sandbox.execute_python(
                code=code,
                timeout=self.timeout,
                benchmark_code=benchmark_code,
            )

        # Measured runs
        for i in range(self.repetitions):
            logger.debug(
                f"Benchmark run {i + 1}/{self.repetitions} for {candidate_id}"
            )
            result = self.sandbox.execute_python(
                code=code,
                timeout=self.timeout,
                benchmark_code=benchmark_code,
            )

            measurement = BenchmarkMeasurement(
                wall_time_seconds=result.duration_seconds,
                exit_code=result.exit_code,
                output_correct=result.success,
                error=result.error,
            )

            # Try to extract structured timing from stdout
            if result.success:
                timing = self._extract_timing(result.stdout)
                if timing is not None:
                    measurement.wall_time_seconds = timing

            measurements.append(measurement)

        return self._aggregate(candidate_id, measurements)

    def _aggregate(
        self,
        candidate_id: str,
        measurements: list[BenchmarkMeasurement],
    ) -> BenchmarkResult:
        """Aggregate individual measurements into a result."""
        valid_times = [
            m.wall_time_seconds for m in measurements
            if m.exit_code == 0 and m.wall_time_seconds > 0
        ]

        if not valid_times:
            return BenchmarkResult(
                candidate_id=candidate_id,
                measurements=measurements,
                warmup_runs=self.warmup_runs,
                measured_runs=self.repetitions,
            )

        return BenchmarkResult(
            candidate_id=candidate_id,
            measurements=measurements,
            warmup_runs=self.warmup_runs,
            measured_runs=len(valid_times),
            median_time=statistics.median(valid_times),
            mean_time=statistics.mean(valid_times),
            std_dev=statistics.stdev(valid_times) if len(valid_times) > 1 else 0.0,
            min_time=min(valid_times),
            max_time=max(valid_times),
            environment={
                "repetitions": str(self.repetitions),
                "warmup_runs": str(self.warmup_runs),
                "timeout": str(self.timeout),
            },
        )

    def _extract_timing(self, stdout: str) -> Optional[float]:
        """Try to extract a timing value from structured output."""
        import json
        try:
            data = json.loads(stdout.strip().split("\n")[-1])
            if isinstance(data, dict) and "benchmark_time" in data:
                return float(data["benchmark_time"])
        except (json.JSONDecodeError, ValueError, IndexError):
            pass
        return None


def compare_benchmarks(
    baseline: BenchmarkResult,
    candidate: BenchmarkResult,
) -> dict:
    """
    Compare baseline and candidate benchmark results.

    Returns a dict with improvement metrics.
    """
    result = {
        "baseline_median": baseline.median_time,
        "candidate_median": candidate.median_time,
        "speed_improvement_percent": 0.0,
        "baseline_mean": baseline.mean_time,
        "candidate_mean": candidate.mean_time,
        "is_faster": False,
    }

    if baseline.median_time > 0:
        improvement = (
            (baseline.median_time - candidate.median_time)
            / baseline.median_time
        ) * 100
        result["speed_improvement_percent"] = round(improvement, 2)
        result["is_faster"] = improvement > 0

    if (baseline.median_memory is not None and candidate.median_memory is not None
            and baseline.median_memory > 0):
        mem_improvement = (
            (baseline.median_memory - candidate.median_memory)
            / baseline.median_memory
        ) * 100
        result["memory_improvement_percent"] = round(mem_improvement, 2)

    return result
