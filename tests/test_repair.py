"""
Tests for Automated Code Repair with local Gemma 2.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mutagen.ai.repair import CodeRepairResult, CodeRepairService


def test_code_repair_service_detect_local_gemma2(monkeypatch):
    svc = CodeRepairService()
    assert "gemma2" in svc.model_id or "gemma" in svc.model_id


def test_extract_code_from_markdown():
    svc = CodeRepairService()
    model_output = """Here is the corrected code:
```python
def add(a, b):
    return a + b
```
Hope this helps!"""
    extracted = svc._extract_code(model_output, "python")
    assert extracted == "def add(a, b):\n    return a + b"


def test_repair_code_mocked_success():
    svc = CodeRepairService()

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "response": "```python\ndef fib(n):\n    if n <= 1: return n\n    return fib(n - 1) + fib(n - 2)\n```"
    }

    with patch("requests.post", return_value=fake_response):
        res = svc.repair_code(
            code="def fib(n): return fib(n-1) + fib(n-3)",
            failures=["Differential regression: expected fib(3)=2, got 1"],
            language="python",
        )

    assert res.success is True
    assert res.changes_made is True
    assert "fib(n - 2)" in res.repaired_code


def test_repair_file_updates_file_on_disk(tmp_path):
    svc = CodeRepairService()
    test_file = tmp_path / "broken.py"
    test_file.write_text("def solve(): return 1 / 0\n", encoding="utf-8")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "response": "```python\ndef solve():\n    return 42\n```"
    }

    with patch("requests.post", return_value=fake_response):
        res = svc.repair_file(
            file_path=test_file,
            failures=["ZeroDivisionError: division by zero"],
            language="python",
        )

    assert res.success is True
    assert res.changes_made is True
    assert "return 42" in test_file.read_text(encoding="utf-8")
