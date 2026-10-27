from pathlib import Path

from tests.eval.trace_report import render

EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "evidence"


def test_renders_one_row_per_case_of_a_committed_trace():
    table = render(EVIDENCE / "agentic-run-1-baseline.jsonl").splitlines()
    assert len(table) == 2 + 22
    assert "— (did not search)" in "\n".join(table)  # the baseline's routing failures


def test_committed_traces_hold_no_local_paths_or_secrets():
    for trace in EVIDENCE.glob("*.jsonl"):
        text = trace.read_text()
        assert "/var/folders" not in text and "/Users/" not in text
        assert "sk-ant" not in text
