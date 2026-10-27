"""Hand-labelled answers for checking the LLM judge before trusting its verdicts.

A judge is a model too, so it gets its own eval. Each case is a fixed agent trace with the label a
careful human would give. They target the ways a lenient judge goes wrong: a related but wrong
skill, a confident recommendation when nothing fits, an invented skill name, and a correct skill
padded with a capability it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass

from tests.eval.agentic import JUDGE_MODEL, AgentRun, ToolCall, catalog_descriptions, judge

_DESC = catalog_descriptions()


def _search(query: str, *names: str) -> ToolCall:
    output = (
        "\n".join(f"{n} (v1) — {_DESC[n]}" for n in names)
        if names
        else f'No skills matched "{query}".'
    )
    return ToolCall("search_skills", {"query": query}, output, False)


@dataclass(frozen=True)
class JudgeCase:
    label: str
    run: AgentRun
    correct: bool
    hallucinated: bool


JUDGE_CASES = [
    JudgeCase(
        "right skill, faithful",
        AgentRun(
            "We just had a production outage, help me write the postmortem.",
            "incident-postmortem",
            [_search("postmortem outage", "incident-postmortem", "oncall-handoff")],
            "The team catalog has `incident-postmortem`, which writes a blameless postmortem "
            "with impact, timeline, root cause and action items. Want me to install it?",
        ),
        correct=True,
        hallucinated=False,
    ),
    JudgeCase(
        "related but wrong skill",
        AgentRun(
            "We just had a production outage, help me write the postmortem.",
            "incident-postmortem",
            [_search("outage", "oncall-handoff", "incident-postmortem")],
            "Use `oncall-handoff`: it summarizes ongoing incidents, which covers your outage.",
        ),
        correct=False,
        # A boundary case. The judge said hallucinated=True on the first run and False on the
        # second, so the rubric was ambiguous here; it now states that claiming a skill "covers"
        # a need its description does not include is a hallucination. The label follows the
        # rubric, and the rubric (not the label) was changed to remove the ambiguity.
        hallucinated=True,
    ),
    JudgeCase(
        "nothing fits, says so",
        AgentRun(
            "Help me with our Kubernetes Helm charts.",
            None,
            [_search("kubernetes helm chart")],
            "There is no skill for Helm charts in the team catalog. I can help directly instead.",
        ),
        correct=True,
        hallucinated=False,
    ),
    JudgeCase(
        "nothing fits, recommends a lexical false positive anyway",
        AgentRun(
            "Generate PDF invoices for our customers.",
            None,
            [_search("pdf invoices customers", "customer-bug-report")],
            "Yes: `customer-bug-report` handles customer documents, so it can generate the "
            "invoices.",
        ),
        correct=False,
        hallucinated=True,
    ),
    JudgeCase(
        "nothing fits, mentions the closest and rules it out",
        AgentRun(
            "Generate PDF invoices for our customers.",
            None,
            [_search("pdf invoices customers", "customer-bug-report")],
            "No catalog skill generates invoices. The only hit, `customer-bug-report`, turns "
            "support tickets into bug reports, so it does not fit.",
        ),
        correct=True,
        hallucinated=False,
    ),
    JudgeCase(
        "invented skill name",
        AgentRun(
            "Help me write the release notes for v2.3.",
            "release-note-draft",
            [_search("release notes", "release-note-draft")],
            "Install `changelog-generator` from the catalog; it writes release notes.",
        ),
        correct=False,
        hallucinated=True,
    ),
    JudgeCase(
        "right skill, padded with a capability it lacks",
        AgentRun(
            "Help me write the release notes for v2.3.",
            "release-note-draft",
            [_search("release notes", "release-note-draft")],
            "Use `release-note-draft`. It drafts the notes from merged pull requests and also "
            "publishes them to GitHub Releases and Slack automatically.",
        ),
        correct=True,
        hallucinated=True,
    ),
]


async def calibrate(client, model: str = JUDGE_MODEL) -> tuple[float, list[str]]:
    """Fraction of cases where the judge matches both hand labels, and the ones it missed."""
    disagreements = []
    for case in JUDGE_CASES:
        verdict = await judge(client, case.run, _DESC, model)
        if (verdict.correct, verdict.hallucinated) != (case.correct, case.hallucinated):
            disagreements.append(
                f"{case.label}: judge said correct={verdict.correct}, "
                f"hallucinated={verdict.hallucinated} ({verdict.reasoning})"
            )
    return 1 - len(disagreements) / len(JUDGE_CASES), disagreements
