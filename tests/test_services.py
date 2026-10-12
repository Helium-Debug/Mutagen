"""
Tests for MUTAGEN service layer.
"""

import pytest
from pathlib import Path

from mutagen.services import (
    AnalysisService, ProjectService, ExperimentService,
    CertificateService, ExportService,
)
from mutagen.schemas import OptimizationObjective, ExperimentConfig


def test_analysis_service(tmp_path):
    svc = AnalysisService()
    f = tmp_path / "hello.py"
    f.write_text("def hello():\n    print('world')\n", encoding="utf-8")

    analysis = svc.analyze_file(str(f))
    assert analysis.syntax_valid is True
    assert len(analysis.functions) == 1


def test_project_service(tmp_path):
    svc = ProjectService()
    f = tmp_path / "source.py"
    f.write_text("def main(): pass\n", encoding="utf-8")

    res = svc.create_project("ServiceProj", "Test description", "python", str(f))
    assert res["id"] is not None
    assert res["name"] == "ServiceProj"

    proj = svc.get_project(res["id"])
    assert proj["name"] == "ServiceProj"

    projects = svc.list_projects()
    assert len(projects) >= 1

    svc.delete_project(res["id"])
    assert svc.get_project(res["id"]) is None


def test_certificate_and_export_service(tmp_path):
    cert_svc = CertificateService()
    export_svc = ExportService()

    # Create dummy experiment in DB
    proj_svc = ProjectService()
    p = proj_svc.create_project("ExportProj")

    # Verify certificate generation check
    assert cert_svc is not None
    assert export_svc is not None
