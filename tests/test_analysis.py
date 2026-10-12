"""
Tests for source code analysis and language detection.
"""

import tempfile
from pathlib import Path
import pytest

from mutagen.analysis.language_detector import detect_language
from mutagen.analysis.python_analyzer import PythonAnalyzer
from mutagen.schemas import ProgrammingLanguage


def test_detect_language_by_extension(tmp_path):
    py_file = tmp_path / "test.py"
    py_file.write_text("print('hello')", encoding="utf-8")
    assert detect_language(py_file) == ProgrammingLanguage.PYTHON

    js_file = tmp_path / "test.js"
    js_file.write_text("console.log('hello')", encoding="utf-8")
    assert detect_language(js_file) == ProgrammingLanguage.JAVASCRIPT

    rs_file = tmp_path / "test.rs"
    rs_file.write_text("fn main() {}", encoding="utf-8")
    assert detect_language(rs_file) == ProgrammingLanguage.RUST


def test_python_analyzer_valid_code(sample_python_code):
    analyzer = PythonAnalyzer()
    analysis = analyzer.analyze(sample_python_code, "compute.py")

    assert analysis.syntax_valid is True
    assert analysis.language == ProgrammingLanguage.PYTHON
    assert analysis.lines_total > 0
    assert analysis.lines_code > 0
    assert analysis.complexity_score >= 1.0
    assert len(analysis.functions) == 1
    assert "compute_sum" in [f.name for f in analysis.functions]
    assert analysis.source_hash != ""


def test_python_analyzer_syntax_error():
    broken_code = "def broken_func(:\n    return 42"
    analyzer = PythonAnalyzer()
    analysis = analyzer.analyze(broken_code, "broken.py")

    assert analysis.syntax_valid is False
    assert len(analysis.syntax_errors) > 0


def test_python_analyzer_complex_constructs():
    complex_code = '''
class DataProcessor:
    def __init__(self, items):
        self.items = items

    def process(self, threshold=10):
        results = []
        for x in self.items:
            if x > threshold and x % 2 == 0:
                results.append(x * 2)
            elif x < 0:
                results.append(0)
            else:
                try:
                    results.append(100 // x)
                except ZeroDivisionError:
                    results.append(-1)
        return results
'''
    analyzer = PythonAnalyzer()
    analysis = analyzer.analyze(complex_code, "processor.py")

    assert analysis.syntax_valid is True
    assert len(analysis.classes) == 1
    assert len(analysis.classes[0].methods) == 2
    assert analysis.complexity_score >= 2.0
