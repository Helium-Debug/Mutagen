"""
Language detection for MUTAGEN.

Detects the programming language of a source file using extension mapping
and content inspection heuristics.
"""

from __future__ import annotations

from pathlib import Path

from mutagen.schemas import ProgrammingLanguage

# Extension to language mapping
EXTENSION_MAP: dict[str, ProgrammingLanguage] = {
    ".py": ProgrammingLanguage.PYTHON,
    ".pyw": ProgrammingLanguage.PYTHON,
    ".js": ProgrammingLanguage.JAVASCRIPT,
    ".mjs": ProgrammingLanguage.JAVASCRIPT,
    ".cjs": ProgrammingLanguage.JAVASCRIPT,
    ".jsx": ProgrammingLanguage.JAVASCRIPT,
    ".ts": ProgrammingLanguage.TYPESCRIPT,
    ".tsx": ProgrammingLanguage.TYPESCRIPT,
    ".java": ProgrammingLanguage.JAVA,
    ".c": ProgrammingLanguage.C,
    ".h": ProgrammingLanguage.C,
    ".cpp": ProgrammingLanguage.CPP,
    ".hpp": ProgrammingLanguage.CPP,
    ".cc": ProgrammingLanguage.CPP,
    ".cxx": ProgrammingLanguage.CPP,
    ".go": ProgrammingLanguage.GO,
    ".rs": ProgrammingLanguage.RUST,
}

# Content-based heuristics (checked in order)
CONTENT_HEURISTICS: list[tuple[str, ProgrammingLanguage]] = [
    ("#!/usr/bin/env python", ProgrammingLanguage.PYTHON),
    ("#!/usr/bin/python", ProgrammingLanguage.PYTHON),
    ("import ", ProgrammingLanguage.PYTHON),  # Weak signal, checked last
    ("def ", ProgrammingLanguage.PYTHON),
    ("class ", ProgrammingLanguage.PYTHON),
    ("function ", ProgrammingLanguage.JAVASCRIPT),
    ("const ", ProgrammingLanguage.JAVASCRIPT),
    ("package main", ProgrammingLanguage.GO),
    ("fn main", ProgrammingLanguage.RUST),
    ("public static void main", ProgrammingLanguage.JAVA),
    ("#include", ProgrammingLanguage.C),
]


def detect_language(file_path: str | Path, content: str | None = None) -> ProgrammingLanguage:
    """
    Detect the programming language of a source file.

    Uses file extension as primary signal, falls back to content inspection.

    Args:
        file_path: Path to the source file.
        content: Optional file content for heuristic analysis.

    Returns:
        The detected programming language.
    """
    path = Path(file_path)

    # Primary: extension-based detection
    ext = path.suffix.lower()
    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext]

    # Secondary: content-based heuristics
    if content:
        for pattern, language in CONTENT_HEURISTICS:
            if pattern in content:
                return language

    return ProgrammingLanguage.UNKNOWN


def is_execution_supported(language: ProgrammingLanguage) -> bool:
    """Check if sandboxed execution is implemented for this language."""
    # Currently only Python has sandbox support
    return language == ProgrammingLanguage.PYTHON


def get_file_extension(language: ProgrammingLanguage) -> str:
    """Get the canonical file extension for a language."""
    ext_map = {
        ProgrammingLanguage.PYTHON: ".py",
        ProgrammingLanguage.JAVASCRIPT: ".js",
        ProgrammingLanguage.TYPESCRIPT: ".ts",
        ProgrammingLanguage.JAVA: ".java",
        ProgrammingLanguage.C: ".c",
        ProgrammingLanguage.CPP: ".cpp",
        ProgrammingLanguage.GO: ".go",
        ProgrammingLanguage.RUST: ".rs",
    }
    return ext_map.get(language, ".txt")
