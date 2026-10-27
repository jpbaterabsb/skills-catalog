"""Agentic eval: a real model, in a real tool loop, against the real MCP server.

The discovery eval fixes the search query. This one does not: each developer need goes to an
agent model (Claude Haiku 5.5 by default) that sees the catalog only through the six MCP tools,
exactly as an assistant would. Every step is recorded (tool name, arguments, output), then graded
two ways:

- **Code-graded** from the trace: did the agent search, which terms did it send, did the right
  skill come back first.
- **LLM-as-judge** (Claude Opus 5.5 by default) on the final answer, against a fixed rubric, with
  structured JSON output: did it recommend the right skill (or clearly say none fits), and did it
  invent skills or capabilities that the tools never returned.

The judge is itself checked against hand-labelled answers (``judge_cases.py``) before its verdicts
are trusted.

Requires credentials for the Claude API: put ``ANTHROPIC_API_KEY`` in ``.env`` (see
``.env.example``) or in the environment. Run with:

    uv run --group eval python -m tests.eval.agentic

Each run spends real money (estimated and printed at the end) and writes a JSONL trace per case
to ``.eval-runs/``.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import anyio
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from skills_catalog.adapter.client import CatalogClient
from skills_catalog.adapter.server import INSTRUCTIONS, build_server
from skills_catalog.api.app import create_app
from tests.eval.cases import CASES, Case
from tests.eval.discovery import catalog_bundles

REPO = Path(__file__).resolve().parents[2]
AGENT_MODEL = "claude-haiku-5-5"
JUDGE_MODEL = "claude-opus-5-5"
MAX_TURNS = 8
CONCURRENCY = 4
# USD per million tokens (input, output), for the cost estimate printed after a run.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-opus-5-5": (4.00, 20.00)}

AGENT_SYSTEM = f"""You are an AI coding assistant working in a developer's repository.
You can use the team's shared skills catalog through the tools provided.
Answer the developer's request. When you recommend a skill, name it exactly.

About the skills catalog:
{INSTRUCTIONS}"""

JUDGE_SYSTEM = """You grade answers from an AI coding assistant that can search a team catalog of
skills (reusable instructions). You receive the developer's need, the skill that should be
recommended (or "none" when nothing in the catalog fits), the full catalog, the assistant's tool
calls with their outputs, and the assistant's final answer.

Rubric:
- correct = true when the final answer recommends the expected skill as the way to address the
  need. When the expected skill is "none", correct = true only if the answer clearly says no
  catalog skill fits; mentioning a loosely related skill is fine only if the answer says it does
  not fit. Recommending a different skill as the main answer is incorrect, even if it is related.
- hallucinated = true when the answer names a skill that does not appear in any tool output, or
  attributes to a skill a capability its description does not support.
Judge only the final answer against the tool outputs; do not reward effort or style.
Explain your reasoning in one or two sentences."""

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "correct": {"type": "boolean"},
        "hallucinated": {"type": "boolean"},
    },
    "required": ["reasoning", "correct", "hallucinated"],
    "additionalProperties": False,
}


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    output: str
    is_error: bool


@dataclass
class AgentRun:
    need: str
    expected: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_text: str = ""
    turns: int = 0
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def searches(self) -> list[ToolCall]:
        return [c for c in self.tool_calls if c.name == "search_skills"]

    @property
    def searched(self) -> bool:
        return bool(self.searches)

    @property
    def first_search_top(self) -> str | None:
        """Name of the first result of the first search, or None if it found nothing."""
        if not self.searches or self.searches[0].is_error:
            return None
        first_line = self.searches[0].output.splitlines()[0]
        return None if first_line.startswith("No skills matched") else first_line.split(" (v")[0]


@dataclass
class Verdict:
    correct: bool
    hallucinated: bool
    reasoning: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CaseOutcome:
    run: AgentRun
    verdict: Verdict

    @property
    def retrieval_correct(self) -> bool:
        """Code-graded: the agent searched, and its first search put the expected skill first
        (or, when nothing fits, found nothing). Not searching is never a correct retrieval."""
        return self.run.searched and self.run.first_search_top == self.run.expected


# --- agent loop ------------------------------------------------------------------------------


def tool_definitions(mcp_tools) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
        for t in mcp_tools
    ]


async def run_agent(
    client, session: ClientSession, need: str, expected: str | None, model: str = AGENT_MODEL
) -> AgentRun:
    """A manual tool loop (rather than the SDK's beta tool runner) so every tool call and its
    exact output can be recorded for grading and debugging."""
    run = AgentRun(need=need, expected=expected)
    tools = tool_definitions((await session.list_tools()).tools)
    messages: list[dict[str, Any]] = [{"role": "user", "content": need}]

    for _ in range(MAX_TURNS):
        response = await client.messages.create(
            model=model,
            max_tokens=16000,
            system=AGENT_SYSTEM,
            tools=tools,
            messages=messages,
            output_config={"effort": "medium"},
        )
        run.turns += 1
        run.stop_reason = response.stop_reason
        run.input_tokens += response.usage.input_tokens
        run.output_tokens += response.usage.output_tokens
        texts = [b.text for b in response.content if b.type == "text"]
        if texts:
            run.final_text = "\n".join(texts)
        if response.stop_reason != "tool_use":
            break

        # Append the full content (thinking blocks included) so the next turn stays valid.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in (b for b in response.content if b.type == "tool_use"):
            result = await session.call_tool(block.name, block.input)
            output = "\n".join(c.text for c in result.content if c.type == "text")
            run.tool_calls.append(ToolCall(block.name, dict(block.input), output, result.isError))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": bool(result.isError),
                }
            )
        # All results of one turn go back in a single user message.
        messages.append({"role": "user", "content": results})
    return run


# --- LLM as judge ----------------------------------------------------------------------------


def judge_prompt(run: AgentRun, catalog: dict[str, str]) -> str:
    calls = "\n\n".join(
        f"[{c.name}] input={json.dumps(c.input)}{' (error)' if c.is_error else ''}\n{c.output}"
        for c in run.tool_calls
    )
    listing = "\n".join(f"- {name}: {desc}" for name, desc in sorted(catalog.items()))
    return (
        f"<need>{run.need}</need>\n"
        f"<expected_skill>{run.expected or 'none'}</expected_skill>\n"
        f"<catalog>\n{listing}\n</catalog>\n"
        f"<tool_calls>\n{calls or '(no tool calls)'}\n</tool_calls>\n"
        f"<final_answer>\n{run.final_text or '(empty)'}\n</final_answer>"
    )


async def judge(
    client, run: AgentRun, catalog: dict[str, str], model: str = JUDGE_MODEL
) -> Verdict:
    response = await client.messages.create(
        model=model,
        max_tokens=4000,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": judge_prompt(run, catalog)}],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": VERDICT_SCHEMA},
        },
    )
    if response.stop_reason == "refusal":
        # No silent fallback to another judge model: a different judge is a different measurement.
        raise RuntimeError(f"judge refused to grade: {run.need!r}")
    data = json.loads(next(b.text for b in response.content if b.type == "text"))
    return Verdict(
        correct=data["correct"],
        hallucinated=data["hallucinated"],
        reasoning=data["reasoning"],
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


# --- orchestration ---------------------------------------------------------------------------


def catalog_descriptions() -> dict[str, str]:
    from skills_catalog.core.validation import parse_skill_md

    return {
        name: parse_skill_md(files["SKILL.md"])[0].description
        for name, files in catalog_bundles().items()
    }


async def run_eval(
    client,
    cases: list[Case] = CASES,
    agent_model: str = AGENT_MODEL,
    judge_model: str = JUDGE_MODEL,
) -> list[CaseOutcome]:
    """Run every case through the agent and the judge, against an in-process catalog."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(Path(tmp) / "catalog")
        for files in catalog_bundles().values():
            app.state.service.publish(files, "eval")
        catalog = catalog_descriptions()
        outcomes: list[CaseOutcome | None] = [None] * len(cases)
        limiter = anyio.CapacityLimiter(CONCURRENCY)

        async def one(i: int, case: Case) -> None:
            project = Path(tmp) / f"project-{i}"  # installs from one case never leak to another
            project.mkdir()
            server = build_server(
                lambda: CatalogClient("http://testserver", http=TestClient(app)), lambda: project
            )
            async with limiter, create_connected_server_and_client_session(server) as session:
                run = await run_agent(client, session, case.need, case.expected, agent_model)
                outcomes[i] = CaseOutcome(run, await judge(client, run, catalog, judge_model))

        async with anyio.create_task_group() as tg:
            for i, case in enumerate(cases):
                tg.start_soon(one, i, case)
    return [o for o in outcomes if o is not None]


@dataclass
class Summary:
    cases: int
    searched: float
    retrieval_correct: float
    retrieval_when_searched: float
    judge_correct: float
    hallucinated: float
    avg_tool_calls: float
    cost_usd: float


def summarize(outcomes: list[CaseOutcome], agent_model: str, judge_model: str) -> Summary:
    n = len(outcomes)

    def cost(model: str, inp: int, out: int) -> float:
        price_in, price_out = PRICES.get(model, (0.0, 0.0))
        return (inp * price_in + out * price_out) / 1_000_000

    return Summary(
        cases=n,
        searched=sum(o.run.searched for o in outcomes) / n,
        retrieval_correct=sum(o.retrieval_correct for o in outcomes) / n,
        retrieval_when_searched=(
            sum(o.retrieval_correct for o in outcomes)
            / max(1, sum(o.run.searched for o in outcomes))
        ),
        judge_correct=sum(o.verdict.correct for o in outcomes) / n,
        hallucinated=sum(o.verdict.hallucinated for o in outcomes) / n,
        avg_tool_calls=sum(len(o.run.tool_calls) for o in outcomes) / n,
        cost_usd=sum(
            cost(agent_model, o.run.input_tokens, o.run.output_tokens)
            + cost(judge_model, o.verdict.input_tokens, o.verdict.output_tokens)
            for o in outcomes
        ),
    )


def write_trace(outcomes: list[CaseOutcome], directory: Path) -> Path:
    """One JSON line per case: the full step-by-step trace plus both grades."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"agentic-{time.strftime('%Y%m%dT%H%M%S')}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for o in outcomes:
            record = {
                **asdict(o.run),
                "verdict": asdict(o.verdict),
                "retrieval_correct": o.retrieval_correct,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def load_dotenv(path: Path = REPO / ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines) so the eval needs no extra dependency.
    Values already in the environment win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def models_from_env() -> tuple[str, str]:
    return (
        os.environ.get("SKILLS_EVAL_AGENT_MODEL", AGENT_MODEL),
        os.environ.get("SKILLS_EVAL_JUDGE_MODEL", JUDGE_MODEL),
    )


def main() -> None:
    import logging

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        raise SystemExit(
            "The agentic eval needs the eval dependency group:\n"
            "  uv run --group eval python -m tests.eval.agentic"
        ) from None

    from tests.eval.judge_cases import calibrate

    logging.disable(logging.INFO)
    load_dotenv()
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "note: no ANTHROPIC_API_KEY in the environment or .env (see .env.example); "
            "trying an `ant auth login` profile.\n"
        )
    agent_model, judge_model = models_from_env()
    client = AsyncAnthropic()  # ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant` profile

    try:
        agreement, disagreements = anyio.run(calibrate, client, judge_model)
    except TypeError as exc:  # raised by the SDK when no credential source resolves
        if "authentication" not in str(exc):
            raise
        raise SystemExit(
            "No Claude API credentials: set ANTHROPIC_API_KEY in .env (see .env.example)."
        ) from None
    print(f"### Judge calibration ({judge_model})\n")
    print(f"Agreement with hand labels: {agreement:.0%}")
    for d in disagreements:
        print(f"- disagreed on: {d}")

    outcomes = anyio.run(run_eval, client, CASES, agent_model, judge_model)
    s = summarize(outcomes, agent_model, judge_model)
    trace = write_trace(outcomes, REPO / ".eval-runs")
    print(f"\n### Agentic discovery ({s.cases} needs, agent {agent_model}, judge {judge_model})\n")
    print("| Metric | Value |")
    print("|---|---|")
    print(f"| Agent called `search_skills` | {s.searched:.0%} |")
    print(
        f"| First search ranked the right skill first (code-graded) | {s.retrieval_correct:.0%} |"
    )
    print(f"| Same, counting only needs where it searched | {s.retrieval_when_searched:.0%} |")
    print(f"| Final answer correct (LLM judge) | {s.judge_correct:.0%} |")
    print(f"| Final answer hallucinated a skill or capability (LLM judge) | {s.hallucinated:.0%} |")
    print(f"| Tool calls per need (mean) | {s.avg_tool_calls:.1f} |")
    print(f"| Estimated cost of this run | ${s.cost_usd:.2f} |")
    failures = [o for o in outcomes if not o.verdict.correct or o.verdict.hallucinated]
    for o in failures:
        terms = [c.input.get("query") for c in o.run.searches]
        print(f"\n- `{o.run.need}` searched {terms}: {o.verdict.reasoning}", end="")
    print(f"\n\nStep-by-step trace: {trace.relative_to(REPO)}")


if __name__ == "__main__":
    main()
