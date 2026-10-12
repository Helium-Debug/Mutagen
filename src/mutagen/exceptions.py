"""
MUTAGEN exception hierarchy.

All application-specific exceptions inherit from MutagenError.
Exit codes are defined as class attributes for CLI integration.
"""

from __future__ import annotations


class MutagenError(Exception):
    """Base exception for all MUTAGEN errors."""
    exit_code: int = 1


class MutagenConfigError(MutagenError):
    """Invalid or missing configuration."""
    exit_code: int = 2


class MutagenDependencyError(MutagenError):
    """Required dependency or service unavailable."""
    exit_code: int = 3


class MutagenExperimentError(MutagenError):
    """Experiment execution failure."""
    exit_code: int = 4


class MutagenVerificationError(MutagenError):
    """Verification or certificate failure."""
    exit_code: int = 5


class MutagenValidationError(MutagenError):
    """Input or data validation failure."""
    exit_code: int = 2


class MutagenSandboxError(MutagenError):
    """Sandbox execution failure."""
    exit_code: int = 4


class MutagenAIError(MutagenError):
    """AI provider communication or parsing failure."""
    exit_code: int = 1


class MutagenDatabaseError(MutagenError):
    """Database operation failure."""
    exit_code: int = 1


class MutagenSecurityError(MutagenError):
    """Security policy violation."""
    exit_code: int = 1


class MutagenExportError(MutagenError):
    """Candidate export failure."""
    exit_code: int = 1


class MutagenCancellationError(MutagenError):
    """Operation was cancelled by user or timeout."""
    exit_code: int = 1


class MutagenAuthenticationError(MutagenError):
    """Authentication required or authentication failed."""
    exit_code: int = 1


class MutagenAuthorizationError(MutagenError):
    """User lacks permission to access the requested resource."""
    exit_code: int = 1


class MutagenNotFoundError(MutagenError):
    """Requested resource was not found."""
    exit_code: int = 1

