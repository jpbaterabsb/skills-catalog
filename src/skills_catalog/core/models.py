"""Immutable value objects shared by the core, the API and the adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SkillManifest:
    """The parts of ``SKILL.md`` the catalog cares about."""

    name: str
    description: str
    body: str


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One file of a published version, addressed by the sha256 of its bytes."""

    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class PublishResult:
    name: str
    version: int
    digest: str
    created: bool


@dataclass(frozen=True, slots=True)
class VersionSummary:
    """One line of a skill's history."""

    version: int
    digest: str
    published_by: str
    published_at: str


@dataclass(frozen=True, slots=True)
class SkillVersion:
    """A fully described version: metadata, the ``SKILL.md`` text and the file list."""

    name: str
    version: int
    digest: str
    description: str
    published_by: str
    published_at: str
    skill_md: str
    files: tuple[FileEntry, ...]


@dataclass(frozen=True, slots=True)
class SearchResult:
    name: str
    description: str
    latest_version: int
