"""The agentic eval's own plumbing, tested without a model or credentials: a scripted client
stands in for the Claude API, the MCP server and catalog are real."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from skills_catalog.adapter.client import CatalogClient
from skills_catalog.adapter.server import build_server
from skills_catalog.api.app import create_app
from tests.eval import agentic
from tests.eval.agentic import (
    AgentRun,
    CaseOutcome,
    ToolCall,
    Verdict,
    judge,
    judge_prompt,
    load_dotenv,
    run_agent,
    summarize,
    write_trace,
)
from tests.eval.discovery import catalog_bundles

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def response(content, stop_reason, inp=100, out=20):
    usage = SimpleNamespace(input_tokens=inp, output_tokens=out)
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


class ScriptedClient:
    """Returns canned responses in order and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    async def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=vars)))
        return self.responses.pop(0)


@pytest.fixture
def session_factory(tmp_path):
    app = create_app(tmp_path / "catalog")
    for files in catalog_bundles().values():
        app.state.service.publish(files, "eval")
    server = build_server(
        lambda: CatalogClient("http://testserver", http=TestClient(app)), lambda: tmp_path
    )
    return lambda: create_connected_server_and_client_session(server)


async def test_agent_loop_records_real_tool_outputs(session_factory):
    client = ScriptedClient(
        response(
            [
                text("Let me check."),
                tool_use("t1", "search_skills", {"query": "postmortem outage"}),
            ],
            "tool_use",
        ),
        response([text("Use incident-postmortem.")], "end_turn", inp=300, out=10),
    )
    async with session_factory() as session:
        run = await run_agent(client, session, "We had an outage.", "incident-postmortem")

    assert (run.turns, run.stop_reason, run.final_text) == (
        2,
        "end_turn",
        "Use incident-postmortem.",
    )
    assert (run.input_tokens, run.output_tokens) == (400, 30)
    [call] = run.tool_calls
    assert call.name == "search_skills" and not call.is_error
    assert call.output.startswith("incident-postmortem (v1) — ")
    assert run.first_search_top == "incident-postmortem"

    first, second = client.requests
    assert {t["name"] for t in first["tools"]} >= {"search_skills", "install_skill"}
    assert "skills catalog" in first["system"]
    [result] = second["messages"][-1]["content"]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "t1"
    assert result["content"] == call.output


async def test_tool_errors_are_returned_to_the_model(session_factory):
    client = ScriptedClient(
        response([tool_use("t1", "get_skill", {"name": "nope"})], "tool_use"),
        response([text("That skill does not exist.")], "end_turn"),
    )
    async with session_factory() as session:
        run = await run_agent(client, session, "Get nope.", None)
    assert run.tool_calls[0].is_error
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


async def test_loop_stops_after_max_turns(session_factory, monkeypatch):
    monkeypatch.setattr(agentic, "MAX_TURNS", 2)
    loop = [
        response([tool_use(f"t{i}", "search_skills", {"query": "x"})], "tool_use") for i in range(3)
    ]
    async with session_factory() as session:
        run = await run_agent(ScriptedClient(*loop), session, "x", None)
    assert run.turns == 2


def sample_run(**kw):
    defaults = dict(
        need="Help me with Helm charts.",
        expected=None,
        tool_calls=[
            ToolCall("search_skills", {"query": "helm"}, 'No skills matched "helm".', False)
        ],
        final_text="No skill fits.",
    )
    return AgentRun(**{**defaults, **kw})


async def test_judge_uses_structured_output_and_parses_the_verdict():
    verdict_json = json.dumps(
        {"reasoning": "Says none fits.", "correct": True, "hallucinated": False}
    )
    client = ScriptedClient(response([text(verdict_json)], "end_turn", inp=900, out=40))
    verdict = await judge(client, sample_run(), {"a-skill": "Does a."})
    assert (verdict.correct, verdict.hallucinated, verdict.input_tokens) == (True, False, 900)
    fmt = client.requests[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False


async def test_judge_refusal_is_an_error_not_a_silent_fallback():
    client = ScriptedClient(response([], "refusal"))
    with pytest.raises(RuntimeError, match="judge refused"):
        await judge(client, sample_run(), {})


def test_judge_prompt_contains_everything_the_rubric_needs():
    prompt = judge_prompt(sample_run(), {"a-skill": "Does a."})
    assert "<expected_skill>none</expected_skill>" in prompt
    assert "- a-skill: Does a." in prompt
    assert 'No skills matched "helm".' in prompt
    assert "No skill fits." in prompt


def test_code_graded_retrieval_and_summary():
    good = CaseOutcome(sample_run(), Verdict(True, False, "ok", 1000, 100))
    wrong = CaseOutcome(
        sample_run(
            expected="adr-writer",
            tool_calls=[
                ToolCall("search_skills", {"query": "kafka"}, "pr-description (v1) — x", False)
            ],
        ),
        Verdict(False, True, "wrong", 1000, 100),
    )
    assert good.retrieval_correct and not wrong.retrieval_correct
    s = summarize([good, wrong], "claude-haiku-5-5", "claude-opus-5-5")
    assert (s.cases, s.searched, s.retrieval_correct, s.judge_correct, s.hallucinated) == (
        2,
        1.0,
        0.5,
        0.5,
        0.5,
    )
    assert s.cost_usd > 0


def test_trace_is_one_json_line_per_case(tmp_path):
    outcome = CaseOutcome(sample_run(), Verdict(True, False, "ok"))
    path = write_trace([outcome, outcome], tmp_path / "runs")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["tool_calls"][0]["name"] == "search_skills"
    assert lines[0]["verdict"]["correct"] is True


def test_dotenv_fills_gaps_but_never_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nANTHROPIC_API_KEY=\nSKILLS_EVAL_AGENT_MODEL='claude-x'\nSKILLS_T=keep\n"
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SKILLS_EVAL_AGENT_MODEL", raising=False)
    monkeypatch.setenv("SKILLS_T", "existing")
    load_dotenv(env)
    import os

    assert "ANTHROPIC_API_KEY" not in os.environ  # empty placeholder is ignored
    assert os.environ["SKILLS_EVAL_AGENT_MODEL"] == "claude-x"
    assert os.environ["SKILLS_T"] == "existing"
