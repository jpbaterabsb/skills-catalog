"""Print the eval results as Markdown: ``uv run python -m tests.eval.report``."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from tests.eval.cases import CASES
from tests.eval.context_budget import measure
from tests.eval.discovery import build_catalog, run_discovery


def main() -> None:
    logging.disable(logging.INFO)
    with tempfile.TemporaryDirectory() as tmp:
        service = build_catalog(Path(tmp) / "discovery")
        reports = [
            (split, run_discovery(service, mode, split=split))
            for split in ("dev", "holdout")
            for mode in ("query", "need")
        ]
        budget = measure(Path(tmp) / "budget")

    positives = sum(c.expected is not None for c in CASES)
    print(
        f"### Discovery ({positives} needs with a right answer, {len(CASES) - positives} without)\n"
    )
    print("| Cases | Search input | hit@1 | hit@3 | MRR | no-match correct |")
    print("|---|---|---|---|---|---|")
    labels = {
        "query": "Key terms (what the tool asks for)",
        "need": "Developer's sentence, verbatim",
    }
    for split, r in reports:
        print(
            f"| {split} ({len(r.results)}) | {labels[r.mode]} | {r.hit_at_1:.0%} "
            f"| {r.hit_at_3:.0%} | {r.mrr:.2f} | {r.no_match_accuracy:.0%} |"
        )
    for split, r in reports:
        for f in r.failures:
            print(
                f"\n- {split}, {r.mode}: `{f.text}` → {f.ranking[:3] or 'no match'}"
                f" (expected {f.case.expected or 'no match'})",
                end="",
            )
    print("\n\n### Context budget (estimated tokens, characters / 4)\n")
    print("| What enters the model's context | Tokens |")
    print("|---|---|")
    for what, n in budget.rows():
        print(f"| {what} | {n} |")
    per_skill = budget.avg_real_bundle_tokens
    print(
        f"\nThe two real example skills average {per_skill} tokens with every file. Inlining a "
        f"100-skill catalog would cost about {per_skill * 100:,} tokens; a search stays at "
        f"{len(budget.search.splitlines())} lines whatever the catalog size."
    )


if __name__ == "__main__":
    main()
