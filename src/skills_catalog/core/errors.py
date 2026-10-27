"""Domain errors.

Every error a caller can act on derives from :class:`CatalogError`, so transports (HTTP, MCP, CLI)
can map the whole family to a response in one place.
"""

from __future__ import annotations

from collections.abc import Iterable


class CatalogError(Exception):
    """Base class for all domain errors."""


class ValidationError(CatalogError):
    """A skill bundle violates the format rules. Carries every violation, not just the first."""

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors: list[str] = list(errors)
        super().__init__("; ".join(self.errors) or "invalid skill bundle")


class NotFoundError(CatalogError):
    """A requested skill, version or blob does not exist."""


class SkillNotFoundError(NotFoundError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"skill '{name}' not found")


class VersionNotFoundError(NotFoundError):
    def __init__(self, name: str, version: int) -> None:
        self.name = name
        self.version = version
        super().__init__(f"skill '{name}' has no version {version}")


class BlobNotFoundError(NotFoundError):
    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256
        super().__init__(f"blob {sha256} not found")
