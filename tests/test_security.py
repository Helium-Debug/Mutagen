"""
Tests for security, input validation, and cryptographic certificate verification.
"""

import pytest

from mutagen.core.security import compute_content_hash, validate_source_content
from mutagen.exceptions import MutagenValidationError
from mutagen.services import CertificateService
from mutagen.schemas import OptimizationCertificate, OptimizationObjective


def test_content_hashing_consistency():
    content1 = "print('hello world')"
    content2 = "print('hello world')"
    content3 = "print('hello world!')"

    hash1 = compute_content_hash(content1)
    hash2 = compute_content_hash(content2)
    hash3 = compute_content_hash(content3)

    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 64  # SHA-256


def test_validate_source_content_size_limit():
    small_content = "x = 1\n"
    validate_source_content(small_content, max_size=100)

    huge_content = "x = 1\n" * 1000
    with pytest.raises(MutagenValidationError):
        validate_source_content(huge_content, max_size=100)


def test_certificate_generation_and_tamper_detection(db_session, sample_python_code):
    from mutagen.db.repositories import ExperimentRepository, CandidateRepository, CertificateRepository
    from mutagen.schemas import CandidateStatus, ExperimentStatus

    exp_repo = ExperimentRepository(db_session)
    cand_repo = CandidateRepository(db_session)

    source_hash = compute_content_hash(sample_python_code)
    cand_code = "def compute_sum(numbers: list[int]) -> int:\n    return sum(numbers)\n"
    cand_hash = compute_content_hash(cand_code)

    exp_repo.create(
        id="exp_cert_123",
        source_file="compute.py",
        source_hash=source_hash,
        source_content=sample_python_code,
        language="python",
        status=ExperimentStatus.SUCCEEDED.value,
        generations_completed=3,
        total_candidates=6,
    )

    cand_repo.create(
        id="cand_cert_123",
        experiment_id="exp_cert_123",
        generation_number=2,
        source_code=cand_code,
        content_hash=cand_hash,
        strategy="vectorization",
        status=CandidateStatus.BEST_ELIGIBLE.value,
        validation_passed=True,
        tests_passed=True,
        speed_improvement=75.0,
        fitness_score=0.92,
        is_eligible=True,
    )
    db_session.commit()

    cert_service = CertificateService()
    cert_data = cert_service.generate_certificate("exp_cert_123")
    assert cert_data is not None
    assert cert_data["speed_improvement_percent"] == 75.0

    # Verify certificate integrity
    verify_result = cert_service.verify_certificate("exp_cert_123")
    assert verify_result["verified"] is True
    assert verify_result["content_hash_valid"] is True
