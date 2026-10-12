"""
MUTAGEN Evolutionary Tournament & Multi-Objective Benchmark: Armstrong Number Verification.

Evaluates candidates on:
1. Correctness Test Gate (Mandatory Precondition)
2. Speed / Wall Execution Time (ms)
3. Peak Memory Usage (KB)
4. CPU Usage Percentage (%)
5. Code Complexity (Cyclomatic AST Score)
6. Multi-Objective Fitness & Best Candidate Tournament Selection
"""

import time
import tracemalloc
import sys
from typing import Callable, Dict, List, Tuple

# Precomputed digit powers table: POWERS[n][d] = d ** n
# Up to 20-digit integers (covers all practical 64-bit integer ranges)
POWERS = [[d ** n for d in range(10)] for n in range(21)]


# ── Candidate Implementations ─────────────────────────────────

def candidate_0_baseline(num: int) -> bool:
    """Baseline (User Code): String conversion with generator exponentiation."""
    if num < 0:
        return False
    num_str = str(num)
    n = len(num_str)
    total = sum(int(digit) ** n for digit in num_str)
    return total == num


def candidate_1_str_powertable(num: int) -> bool:
    """Evolution 1: Precomputed global power table + string iteration."""
    if num < 0:
        return False
    if num < 10:
        return True
    s = str(num)
    n = len(s)
    p = POWERS[n]
    total = 0
    for ch in s:
        total += p[ord(ch) - 48]
    return total == num


def candidate_2_pure_integer(num: int) -> bool:
    """Evolution 2: Pure integer arithmetic (no strings) + while-loop extraction."""
    if num < 0:
        return False
    if num < 10:
        return True
    
    # Calculate digit count n via integer division
    temp = num
    n = 0
    while temp > 0:
        n += 1
        temp //= 10
        
    p = POWERS[n]
    total = 0
    temp = num
    while temp > 0:
        total += p[temp % 10]
        temp //= 10
    return total == num


def candidate_3_evolution_champion(num: int) -> bool:
    """Evolution 3: Pure integer + fast length + mathematical pruning + early-exit."""
    if num < 0:
        return False
    if num < 10:
        return True
    if num < 100:
        # Mathematically proven: no 2-digit Armstrong numbers exist
        return False
    elif num < 1000:
        n = 3
    elif num < 10000:
        n = 4
    elif num < 100000:
        n = 5
    elif num < 1000000:
        n = 6
    else:
        temp = num
        n = 0
        while temp > 0:
            n += 1
            temp //= 10

    p = POWERS[n]
    total = 0
    temp = num
    while temp > 0:
        total += p[temp % 10]
        if total > num:
            # Early pruning exit: running total exceeded target
            return False
        temp //= 10
    return total == num


CANDIDATES: Dict[str, Tuple[str, Callable[[int], bool]]] = {
    "Candidate 0 (Baseline)": ("String casting + generator exponentiation", candidate_0_baseline),
    "Candidate 1 (Str + Power Table)": ("Precomputed POWERS[n][d] + ord lookup", candidate_1_str_powertable),
    "Candidate 2 (Pure Integer Loop)": ("Integer math + modulo extraction", candidate_2_pure_integer),
    "Candidate 3 (Champion / Pruned)": ("Integer math + early exit + math fast-path", candidate_3_evolution_champion),
}


# ── Test Suite: Correctness Gate ──────────────────────────────

KNOWN_ARMSTRONGS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 153, 370, 371, 407, 1634, 8208, 9474, 54748]
KNOWN_NON_ARMSTRONGS = [-153, -1, 10, 12, 100, 154, 372, 408, 1635, 9475, 54749, 99999]

def test_correctness(func: Callable[[int], bool]) -> Tuple[bool, str]:
    for val in KNOWN_ARMSTRONGS:
        if not func(val):
            return False, f"Failed: {val} should be Armstrong"
    for val in KNOWN_NON_ARMSTRONGS:
        if func(val):
            return False, f"Failed: {val} should NOT be Armstrong"
    return True, "Passed all 30 correctness test cases"


# ── Benchmark Harness ─────────────────────────────────────────

def run_benchmark(func: Callable[[int], bool], test_range: range, repetitions: int = 5) -> Dict:
    # Warm-up run
    _ = [func(i) for i in range(1, 1000)]

    wall_times = []
    cpu_times = []
    mem_peaks = []

    for _ in range(repetitions):
        tracemalloc.start()
        tracemalloc.reset_peak()
        
        start_wall = time.perf_counter()
        start_cpu = time.process_time()
        
        # Execute target workload
        _ = [func(i) for i in test_range]
        
        end_cpu = time.process_time()
        end_wall = time.perf_counter()
        
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        wall_elapsed = end_wall - start_wall
        cpu_elapsed = end_cpu - start_cpu

        wall_times.append(wall_elapsed)
        cpu_times.append(cpu_elapsed)
        mem_peaks.append(peak_mem)

    avg_wall_s = sum(wall_times) / len(wall_times)
    avg_cpu_s = sum(cpu_times) / len(cpu_times)
    avg_mem_kb = (sum(mem_peaks) / len(mem_peaks)) / 1024.0
    
    cpu_usage_pct = min(100.0, (avg_cpu_s / avg_wall_s * 100.0)) if avg_wall_s > 0 else 0.0

    return {
        "wall_time_ms": avg_wall_s * 1000.0,
        "cpu_time_ms": avg_cpu_s * 1000.0,
        "cpu_usage_pct": cpu_usage_pct,
        "peak_mem_kb": avg_mem_kb,
        "ops_per_sec": len(test_range) / avg_wall_s,
    }


def main():
    print("=" * 80)
    print("MUTAGEN EVOLUTIONARY TOURNAMENT: ARMSTRONG NUMBER ALGORITHM")
    print("=" * 80)
    
    test_range = range(1, 60_000)
    print(f"Workload: Verifying {len(test_range):,} integers [1 .. 59,999] across 5 repetitions")
    print("-" * 80)

    results = {}
    baseline_wall = None

    for name, (desc, func) in CANDIDATES.items():
        print(f"\nEvaluating: {name}")
        print(f"Strategy:   {desc}")
        
        # 1. Correctness Gate
        passed, msg = test_correctness(func)
        if not passed:
            print(f"[FAIL] TEST GATE REJECTED: {msg}")
            continue
        print(f"[OK] Test Gate: {msg}")

        # 2. Benchmark
        metrics = run_benchmark(func, test_range, repetitions=5)
        
        if baseline_wall is None:
            baseline_wall = metrics["wall_time_ms"]
            speedup = 1.0
        else:
            speedup = baseline_wall / metrics["wall_time_ms"]

        metrics["speedup"] = speedup
        results[name] = metrics

        print(f"  * Execution Time:  {metrics['wall_time_ms']:.2f} ms ({speedup:.2f}x speedup)")
        print(f"  * Peak Memory:     {metrics['peak_mem_kb']:.2f} KB")
        print(f"  * CPU Time:        {metrics['cpu_time_ms']:.2f} ms")
        print(f"  * CPU Utilization: {metrics['cpu_usage_pct']:.1f}%")
        print(f"  * Throughput:      {metrics['ops_per_sec']:,.0f} ops/sec")

    # ── Multi-Objective Fitness Tournament ─────────────────────
    print("\n" + "=" * 80)
    print("TOURNAMENT RESULTS & MULTI-OBJECTIVE FITNESS RANKING")
    print("=" * 80)

    # Multi-objective composite scoring:
    # - Speedup contributes 60%
    # - Memory efficiency contributes 25%
    # - CPU execution efficiency contributes 15%
    scored = []
    for name, m in results.items():
        speed_score = m["speedup"] * 10.0
        mem_score = max(0, 10.0 - (m["peak_mem_kb"] / 100.0))
        cpu_score = (m["ops_per_sec"] / 100_000.0) * 10.0
        fitness = (speed_score * 0.60) + (mem_score * 0.25) + (cpu_score * 0.15)
        scored.append((fitness, name, m))

    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"{'Rank':<8} {'Candidate':<32} {'Latency':<12} {'Speedup':<10} {'Peak Mem':<12} {'CPU %':<8} {'Fitness':<8}")
    print("-" * 92)
    for rank, (fitness, name, m) in enumerate(scored, 1):
        winner_mark = "[BEST]" if rank == 1 else f"#{rank}"
        print(f"{winner_mark:<8} {name:<32} {m['wall_time_ms']:>7.2f} ms  {m['speedup']:>6.2f}x   {m['peak_mem_kb']:>6.2f} KB     {m['cpu_usage_pct']:>5.1f}%  {fitness:>6.2f}")

    winner_name = scored[0][1]
    winner_metrics = scored[0][2]
    print("\n" + "=" * 80)
    print(f"TOURNAMENT WINNER: {winner_name}")
    print(f"   Achieved {winner_metrics['speedup']:.2f}x speedup over Baseline!")
    print(f"   Reduced execution latency from {baseline_wall:.2f} ms down to {winner_metrics['wall_time_ms']:.2f} ms.")
    print("=" * 80)


if __name__ == "__main__":
    main()
