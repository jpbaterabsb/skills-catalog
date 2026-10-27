"""The agentic eval against the real Claude API. Opt-in, because every run costs money:

    SKILLS_EVAL_AGENTIC=1 uv run --group eval pytest tests/eval/test_agentic_live.py

Credentials come from ANTHROPIC_API_KEY (environment or .env), ANTHROPIC_AUTH_TOKEN or an
`ant auth login` profile. Thresholds are a starting bar to be re-pinned from measured runs.
"""

import os

import anyio
import pytest

from tests.eval.agentic import CASES, load_dotenv, models_from_env, run_eval, summarize

pytestmark = pytest.mark.skipif(
    os.environ.get("SKILLS_EVAL_AGENTIC") != "1",
    reason="costs money; set SKILLS_EVAL_AGENTIC=1 to run against the Claude API",
)


@pytest.fixture(scope="module")
def client():
    anthropic = pytest.importorskip("anthropic", reason="install with `uv sync --group eval`")
    load_dotenv()
    return anthropic.AsyncAnthropic()


def test_judge_agrees_with_hand_labels(client):
    from tests.eval.judge_cases import JUDGE_CASES, calibrate

    agreement, disagreements = anyio.run(calibrate, client, models_from_env()[1])
    # At most one disagreement before the judge's verdicts are trusted.
    assert agreement >= 1 - 1 / len(JUDGE_CASES), disagreements


def test_agent_finds_the_right_skill_through_mcp(client):
    agent_model, judge_model = models_from_env()
    outcomes = anyio.run(run_eval, client, CASES, agent_model, judge_model)
    s = summarize(outcomes, agent_model, judge_model)
    assert s.searched >= 0.9
    assert s.judge_correct >= 0.8
    assert s.hallucinated <= 0.1
