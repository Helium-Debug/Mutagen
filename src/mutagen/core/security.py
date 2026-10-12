"""
Security utilities for MUTAGEN.

Provides input validation, path safety checks, and content hash generation.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path, PurePosixPath
from typing import Optional

from mutagen.exceptions import MutagenSecurityError, MutagenValidationError

# Maximum sizes
MAX_SOURCE_FILE_SIZE = 1_048_576  # 1 MB
MAX_ARCHIVE_SIZE = 10_485_760  # 10 MB
MAX_FILENAME_LENGTH = 255
MAX_PATH_DEPTH = 10

# Allowed source file extensions
ALLOWED_SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".c", ".cpp", ".h", ".hpp",
    ".go", ".rs", ".rb", ".php",
    ".txt", ".md", ".json", ".yaml", ".yml", ".toml",
}

# Dangerous patterns in filenames
DANGEROUS_FILENAME_PATTERNS = [
    r"\.\.",         # Path traversal
    r"^/",           # Absolute paths
    r"^~",           # Home expansion
    r"[\x00-\x1f]",  # Control characters
    r"\\",           # Backslashes in normalized paths
]


def compute_content_hash(content: str | bytes) -> str:
    """Compute a SHA-256 hash of the given content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def validate_path_safety(path: str | Path, base_dir: Optional[Path] = None) -> Path:
    """
    Validate a file path for safety.

    Checks for path traversal, absolute paths, and dangerous patterns.

    Args:
        path: The path to validate.
        base_dir: If provided, ensure the resolved path stays within this directory.

    Returns:
        The validated, resolved path.

    Raises:
        MutagenSecurityError: If the path is unsafe.
    """
    path_str = str(path)

    # Check for dangerous patterns
    for pattern in DANGEROUS_FILENAME_PATTERNS:
        if re.search(pattern, path_str):
            raise MutagenSecurityError(f"Unsafe path pattern detected: {path_str!r}")

    resolved = Path(path).resolve()

    if base_dir is not None:
        base_resolved = base_dir.resolve()
        try:
            resolved.relative_to(base_resolved)
        except ValueError:
            raise MutagenSecurityError(
                f"Path traversal: {path_str!r} escapes base directory {base_resolved}"
            )

    return resolved


def validate_source_content(content: str, max_size: int = MAX_SOURCE_FILE_SIZE) -> str:
    """
    Validate source code content for safety.

    Args:
        content: Source code text.
        max_size: Maximum allowed size in bytes.

    Returns:
        The validated content.

    Raises:
        MutagenValidationError: If validation fails.
    """
    content_bytes = content.encode("utf-8")

    if len(content_bytes) > max_size:
        raise MutagenValidationError(
            f"Source content exceeds maximum size: "
            f"{len(content_bytes)} > {max_size} bytes"
        )

    if len(content.strip()) == 0:
        raise MutagenValidationError("Source content is empty.")

    # Check for null bytes
    if "\x00" in content:
        raise MutagenValidationError("Source content contains null bytes.")

    return content


def validate_file_extension(filename: str) -> str:
    """Validate that a filename has an allowed source extension."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_SOURCE_EXTENSIONS:
        raise MutagenValidationError(
            f"Unsupported file extension: {ext!r}. "
            f"Allowed: {', '.join(sorted(ALLOWED_SOURCE_EXTENSIONS))}"
        )
    return ext


def sanitize_log_value(value: str, max_length: int = 500) -> str:
    """
    Sanitize a value for safe inclusion in log messages.

    Strips potential secrets and truncates long values.
    """
    # Mask anything that looks like a key or token
    sanitized = re.sub(
        r'(api[_-]?key|token|secret|password|credential)["\s]*[:=]["\s]*\S+',
        r"\1=***REDACTED***",
        value,
        flags=re.IGNORECASE,
    )
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "...[truncated]"
    return sanitized
