"""
Tests for MUTAGEN Programmatic Diff System.

Covers:
- Added lines
- Removed lines
- Modified lines
- Added files (from empty)
- Deleted files (to empty)
- Multiple modified files
- Empty diffs
- Large diffs
- Unicode source files
- Patch export
- Source hash verification
"""

import pytest
from pathlib import Path

from mutagen.services.diff_service import DiffService
from mutagen.core.security import compute_content_hash


def test_diff_added_lines():
    original = "def foo():\n    return 1\n"
    candidate = "def foo():\n    # new comment\n    val = 1\n    return val\n"

    diff = DiffService.compute_unified_diff(original, candidate)
    assert "+    # new comment" in diff
    assert "+    val = 1" in diff

    summary = DiffService.summarize_changes(original, candidate)
    assert summary.lines_added >= 2
    assert summary.files_changed == 1


def test_diff_removed_lines():
    original = "def foo():\n    # old comment\n    unused = 10\n    return 1\n"
    candidate = "def foo():\n    return 1\n"

    diff = DiffService.compute_unified_diff(original, candidate)
    assert "-    # old comment" in diff
    assert "-    unused = 10" in diff

    summary = DiffService.summarize_changes(original, candidate)
    assert summary.lines_removed >= 2
    assert summary.files_changed == 1


def test_diff_modified_lines():
    original = "def sort_items(items):\n    result = []\n    for item in items:\n        result.append(item)\n    return result\n"
    candidate = "def sort_items(items):\n    return list(items)\n"

    diff = DiffService.compute_unified_diff(original, candidate)
    assert "--- Original" in diff
    assert "+++ Optimized" in diff
    assert "-    result = []" in diff
    assert "+    return list(items)" in diff

    summary = DiffService.summarize_changes(original, candidate)
    assert summary.lines_removed > 0
    assert summary.lines_added > 0
    assert "sort_items" in summary.modified_functions


def test_diff_added_file():
    original = ""
    candidate = "def new_feature():\n    return True\n"

    diff = DiffService.compute_unified_diff(original, candidate, fromfile="/dev/null", tofile="b/new_file.py")
    assert "--- /dev/null" in diff
    assert "+++ b/new_file.py" in diff
    assert "+def new_feature():" in diff

    summary = DiffService.summarize_changes(original, candidate)
    assert summary.lines_added == 2
    assert summary.lines_removed == 0


def test_diff_deleted_file():
    original = "def obsolete():\n    pass\n"
    candidate = ""

    diff = DiffService.compute_unified_diff(original, candidate, fromfile="a/old_file.py", tofile="/dev/null")
    assert "--- a/old_file.py" in diff
    assert "+++ /dev/null" in diff
    assert "-def obsolete():" in diff

    summary = DiffService.summarize_changes(original, candidate)
    assert summary.lines_removed == 2
    assert summary.lines_added == 0


def test_diff_multiple_modified_files():
    files = [
        ("src/sorter.py", "def sort_items(x): return sorted(x)", "def sort_items(x): return list(x)"),
        ("src/utils.py", "DEBUG = False", "DEBUG = True"),
    ]

    combined_diff = []
    total_added = 0
    total_removed = 0

    for path, orig, cand in files:
        d = DiffService.compute_unified_diff(orig, cand, fromfile=f"a/{path}", tofile=f"b/{path}")
        combined_diff.append(d)
        s = DiffService.summarize_changes(orig, cand, file_path=path)
        total_added += s.lines_added
        total_removed += s.lines_removed

    full_patch = "\n".join(combined_diff)
    assert "a/src/sorter.py" in full_patch
    assert "a/src/utils.py" in full_patch
    assert total_added == 2
    assert total_removed == 2


def test_diff_empty():
    code = "def identity(x):\n    return x\n"
    diff = DiffService.compute_unified_diff(code, code)
    assert diff == ""

    summary = DiffService.summarize_changes(code, code)
    assert summary.lines_added == 0
    assert summary.lines_removed == 0
    assert summary.files_changed == 0
    assert len(summary.modified_functions) == 0


def test_diff_large_files():
    original_lines = [f"line_{i} = {i}" for i in range(1000)]
    candidate_lines = [f"line_{i} = {i}" for i in range(1000)]
    # Modify lines 500-505
    for i in range(500, 505):
        candidate_lines[i] = f"line_{i} = {i * 2}  # optimized"

    orig_str = "\n".join(original_lines)
    cand_str = "\n".join(candidate_lines)

    diff = DiffService.compute_unified_diff(orig_str, cand_str, context=5)
    assert "-line_500 = 500" in diff
    assert "+line_500 = 1000  # optimized" in diff

    summary = DiffService.summarize_changes(orig_str, cand_str)
    assert summary.lines_added == 5
    assert summary.lines_removed == 5


def test_diff_unicode_content():
    original = '# 🚀 Initialisation du système\nname = "Antigravity"\n'
    candidate = '# 🚀 Initialisation du système optimisé\nname = "Antigravity 2.0"\nprint("こんにちは世界")\n'

    diff = DiffService.compute_unified_diff(original, candidate)
    assert "+print(\"こんにちは世界\")" in diff
    assert "Antigravity 2.0" in diff

    summary = DiffService.summarize_changes(original, candidate)
    assert summary.lines_added >= 2


def test_patch_export_and_read(tmp_path):
    original = "x = 1\n"
    candidate = "x = 2\n"
    diff = DiffService.compute_unified_diff(original, candidate, fromfile="a/file.py", tofile="b/file.py")

    patch_path = tmp_path / "changes.patch"
    exported = DiffService.export_patch_file(diff, patch_path)

    assert exported.exists()
    content = exported.read_text(encoding="utf-8")
    assert content == diff
    assert "-x = 1" in content
    assert "+x = 2" in content


def test_source_hash_verification(tmp_path):
    code = "def compute():\n    return 42\n"
    expected_hash = compute_content_hash(code)

    file_path = tmp_path / "calc.py"
    file_path.write_text(code, encoding="utf-8")

    # Hashes should match (no conflict)
    has_conflict, current = DiffService.check_file_conflict(file_path, expected_hash)
    assert has_conflict is False
    assert current == code

    # Modify file externally
    file_path.write_text("def compute():\n    return 99\n", encoding="utf-8")
    has_conflict, current = DiffService.check_file_conflict(file_path, expected_hash)
    assert has_conflict is True
    assert "99" in current
