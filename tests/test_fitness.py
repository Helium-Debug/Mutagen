"""
Tests for multi-objective fitness evaluation.
"""

import pytest

from mutagen.evolution.fitness import FitnessEvaluator, tournament_selection, calculate_improvement
from mutagen.schemas import (
    BenchmarkResult, FitnessScore, OptimizationObjective,
    TestResult, ValidationResult,
)


def test_fitness_evaluator_correctness_gate():
    evaluator = FitnessEvaluator(objective=OptimizationObjective.SPEED)
    
    validation = ValidationResult(candidate_id="cand_1", is_valid=True)
    failing_test = TestResult(
        candidate_id="cand_1",
        total_tests=5,
        passed=4,
        failed=1,
    )
    
    score = evaluator.evaluate(
        candidate_id="cand_1",
        validation=validation,
        test_result=failing_test,
        benchmark=None,
        baseline_benchmark=None,
    )
    
    assert score.is_eligible is False
    assert score.correctness_score == 0.0
    assert len(score.rejection_reasons) > 0


def test_fitness_evaluator_speed_improvement():
    evaluator = FitnessEvaluator(objective=OptimizationObjective.SPEED)
    
    validation = ValidationResult(candidate_id="cand_fast", is_valid=True)
    passing_test = TestResult(
        candidate_id="cand_fast",
        total_tests=3,
        passed=3,
        failed=0,
    )
    
    baseline_bench = BenchmarkResult(
        candidate_id="baseline",
        median_time=0.100,  # 100ms
        mean_time=0.100,
    )
    
    cand_bench = BenchmarkResult(
        candidate_id="cand_fast",
        median_time=0.020,  # 20ms -> 80% faster
        mean_time=0.020,
    )
    
    score = evaluator.evaluate(
        candidate_id="cand_fast",
        validation=validation,
        test_result=passing_test,
        benchmark=cand_bench,
        baseline_benchmark=baseline_bench,
    )
    
    assert score.is_eligible is True
    assert score.speed_score > 0.5
    assert score.overall_score > 0.0


def test_tournament_selection():
    scores = [
        FitnessScore(candidate_id="cand_low", overall_score=0.2, is_eligible=True),
        FitnessScore(candidate_id="cand_high", overall_score=0.9, is_eligible=True),
        FitnessScore(candidate_id="cand_ineligible", overall_score=0.99, is_eligible=False),
    ]
    
    selected = tournament_selection(scores, tournament_size=3)
    assert selected is not None
    assert selected.candidate_id == "cand_high"


def test_calculate_improvement():
    imp = calculate_improvement(baseline=10.0, candidate=2.0)
    assert imp == 80.0

    imp_slower = calculate_improvement(baseline=10.0, candidate=15.0)
    assert imp_slower == -50.0
