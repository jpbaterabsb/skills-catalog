"""Render an agentic eval trace (JSONL) as a Markdown table, one row per need:

uv run python -m tests.eval.trace_report docs/evidence/agentic-run-2-after-routing-fix.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def render(path: Path) -> str:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    out = [
        "| # | Split | Developer's need | Expected | Searches sent by the agent | Other tools | "
        "Judge |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        searches = [
            c["input"].get("query", "") for c in r["tool_calls"] if c["name"] == "search_skills"
        ]
        others = [
            f"{c['name']}({c['input'].get('name', '')})"
            for c in r["tool_calls"]
            if c["name"] != "search_skills"
        ]
        v = r["verdict"]
        verdict = ("✅ correct" if v["correct"] else "❌ incorrect") + (
            ", ⚠️ hallucinated" if v["hallucinated"] else ""
        )
        out.append(
            f"| {i} | {r.get('split', 'dev')} | {r['need']} | `{r['expected'] or 'none'}` "
            f"| {'; '.join(f'`{q}`' for q in searches) or '— (did not search)'} "
            f"| {', '.join(others) or '—'} | {verdict} |"
        )
    return "\n".join(out)


if __name__ == "__main__":
    print(render(Path(sys.argv[1])))
