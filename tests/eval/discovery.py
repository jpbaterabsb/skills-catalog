"""Discovery eval: is the shared memory recallable? Runs every case in ``cases.py`` against a
real catalog (SQLite FTS5, same code path as the API) and scores the ranking."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from skills_catalog.core.service import CatalogService
from skills_catalog.core.validation import load_skill_dir
from tests.eval.cases import CASES, EXAMPLES, EXTRA_SKILLS, SKILL_BODIES, Case
from tests.helpers import skill_md


def catalog_bundles() -> dict[str, dict[str, bytes]]:
    """The eval catalog: the synthetic skills plus the real examples, read from disk."""
    bundles = {
        name: {"SKILL.md": skill_md(name, desc, SKILL_BODIES[name])}
        for name, desc in EXTRA_SKILLS.items()
    }
    for skill_dir in sorted(p for p in EXAMPLES.iterdir() if p.is_dir()):
        files, manifest = load_skill_dir(skill_dir)
        bundles[manifest.name] = files
    return bundles


def build_catalog(data_dir: Path) -> CatalogService:
    service = CatalogService(data_dir)
    for files in catalog_bundles().values():
        service.publish(files, "eval")
    return service


@dataclass
class CaseResult:
    case: Case
    text: str
    ranking: list[str]

    @property
    def rank(self) -> int | None:
        if self.case.expected in self.ranking:
            return self.ranking.index(self.case.expected) + 1
        return None

    @property
    def correct(self) -> bool:
        if self.case.expected is None:
            return self.ranking == []
        return self.rank == 1


@dataclass
class DiscoveryReport:
    mode: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def positives(self) -> list[CaseResult]:
        return [r for r in self.results if r.case.expected is not None]

    @property
    def negatives(self) -> list[CaseResult]:
        return [r for r in self.results if r.case.expected is None]

    @property
    def hit_at_1(self) -> float:
        return sum(r.rank == 1 for r in self.positives) / len(self.positives)

    @property
    def hit_at_3(self) -> float:
        return sum(r.rank is not None and r.rank <= 3 for r in self.positives) / len(self.positives)

    @property
    def mrr(self) -> float:
        return sum(1 / r.rank for r in self.positives if r.rank) / len(self.positives)

    @property
    def no_match_accuracy(self) -> float:
        return sum(r.ranking == [] for r in self.negatives) / len(self.negatives)

    @property
    def failures(self) -> list[CaseResult]:
        return [r for r in self.results if not r.correct]


def run_discovery(service: CatalogService, mode: str = "query", limit: int = 5) -> DiscoveryReport:
    """``query``: the assistant's reformulated key terms, which is what ``search_skills`` asks for.
    ``need``: the developer's sentence passed verbatim, a lower bound for a model that does not
    reformulate."""
    report = DiscoveryReport(mode)
    for case in CASES:
        text = case.query if mode == "query" else case.need
        report.results.append(CaseResult(case, text, [r.name for r in service.search(text, limit)]))
    return report
