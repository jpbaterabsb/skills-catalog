# Test evidence

What was run, by whom, with what result, and what changed because of it. Everything here can be
reproduced from the repository (commands below each section).

| Evidence | Where | Needs an API key |
|---|---|---|
| Unit and end-to-end suite (191 tests): core, API, CLI, adapter, MCP over stdio, the two-developer setup | `uv run pytest` | No |
| Discovery and context-budget evals (deterministic) | `uv run python -m tests.eval.report` | No |
| Manual two-session test in Claude Code (Alice publishes, Bob discovers, installs and uses) | [docs/demo.md](../demo.md) | Claude Code login |
| Agentic eval with an LLM judge, run 1 (baseline) and run 2 (after the fix) | this page | Yes |

## Manual test in Claude Code

The two-developer walkthrough ([docs/demo.md](../demo.md)) was run by hand with
`./scripts/two-devs.sh` and two Claude Code sessions using Claude Haiku 5.5. The first attempt
surfaced a real bug: a stale catalog process whose data directory had been deleted answered
`/health` with "ok" while every request failed with HTTP 500, and the setup script reused it.
Fixed in `e4bd747` (`/health` now checks storage; scripts track the real server PID), with E2E
tests for both. The second attempt worked end to end.

## Agentic eval: two runs

Agent: Claude Haiku 5.5, seeing the catalog only through the six MCP tools. Judge: Claude Opus 5.5
with a fixed rubric and JSON-schema output, calibrated against seven hand-labelled answers.
Design and caveats: [DESIGN.md §11](../../DESIGN.md) and [docs/NOTES.md](../NOTES.md).

| Metric | Run 1 (baseline, 22 needs) | Run 2 (after the fix, dev 22 + holdout 6) |
|---|---|---|
| Agent called `search_skills` | 77% | 100% / 100% |
| First search ranked the right skill first | 77% (100% when it searched) | 100% / 100% |
| Final answer correct (LLM judge) | 73% | 100% / 100% |
| Final answer hallucinated (LLM judge) | 0% | 0% / 0% |
| Tool calls per need | 1.5 | 2.6 / 3.0 |
| Judge agreement with hand labels | 6 of 7 | 6 of 7 (same case, opposite direction) |
| Cost | $0.24 | $0.35 |

### What run 1 showed and what changed

Reading the trace below case by case separated one product problem from three eval problems:

| Finding | Kind | Fix |
|---|---|---|
| Agent answered 5 needs from general knowledge without consulting the catalog (#5, #8, #11, #12, #21) | **Product**: tool description only fired on "is there a skill for X" | `8aa2797` new trigger: search before any task the team may have a standard way of doing |
| "No match" counted as a correct retrieval when the agent never searched (#21) | Eval metric | `145cc2a` |
| Agent called `oncall-handoff` a stub and declined it (#9); it was right | Eval fixture | `4502ed6` real procedures for synthetic skills |
| Judge disagreed with one hand label | Eval label / rubric | `e88b034`, then `402de21` when the judge flipped on run 2: rubric made explicit |

Six **held-out** needs were written before the description change (`640ea37`) and never used to tune
it. In run 2 they improved as much as the dev needs, so the change generalizes rather than fixing
only the cases that exposed it.

### Run 1 — baseline, case by case

Console output:

```
### Judge calibration (claude-opus-5-5)

Agreement with hand labels: 86%
- disagreed on: related but wrong skill: judge said correct=False, hallucinated=True

### Agentic discovery (22 needs, agent claude-haiku-5-5, judge claude-opus-5-5)

| Agent called `search_skills`                                  | 77%   |
| First search ranked the right skill first (code-graded)       | 82%   |   <- counted a no-search case; 77% after fix 145cc2a
| Final answer correct (LLM judge)                              | 73%   |
| Final answer hallucinated a skill or capability (LLM judge)   | 0%    |
| Tool calls per need (mean)                                    | 1.5   |
| Estimated cost of this run                                    | $0.24 |
```

| # | Split | Developer's need | Expected | Searches sent by the agent | Other tools | Judge |
|---|---|---|---|---|---|---|
| 1 | dev | Help me write the release notes for v2.3. | `release-note-draft` | `release notes` | get_skill(release-note-draft) | ✅ correct |
| 2 | dev | What changed since the last tag? I need a changelog entry. | `release-note-draft` | `changelog entry release notes from git log` | — | ✅ correct |
| 3 | dev | We just had a production outage, help me write the postmortem. | `incident-postmortem` | `postmortem incident review` | get_skill(incident-postmortem) | ✅ correct |
| 4 | dev | I need an RCA document for yesterday's incident. | `incident-postmortem` | `root cause analysis incident postmortem`; `RCA document` | get_skill(incident-postmortem) | ✅ correct |
| 5 | dev | Write a commit message for my staged changes. | `commit-message` | — (did not search) | — | ❌ incorrect |
| 6 | dev | Can you describe this pull request for reviewers? | `pr-description` | `pull request description reviewer summary` | — | ✅ correct |
| 7 | dev | Is this database migration safe to run in production? | `sql-migration-review` | `database migration safety review production` | — | ✅ correct |
| 8 | dev | Will adding this column lock the Postgres table? | `sql-migration-review` | — (did not search) | — | ❌ incorrect |
| 9 | dev | My on-call shift ends soon, prepare the handoff. | `oncall-handoff` | `on-call handoff` | get_skill(oncall-handoff) | ❌ incorrect |
| 10 | dev | We are seeing a spike of 500s since the last deploy. | `api-error-triage` | `incident triage 500 errors after deploy`; `rollback deployment` | — | ✅ correct |
| 11 | dev | Review this terraform plan before I apply it. | `terraform-plan-review` | — (did not search) | — | ❌ incorrect |
| 12 | dev | Does this infra change open a security group or make a bucket public? | `terraform-plan-review` | — (did not search) | — | ❌ incorrect |
| 13 | dev | Bump our dependencies without breaking anything. | `dependency-upgrade` | `dependency upgrade bump dependencies safely` | get_skill(dependency-upgrade) | ✅ correct |
| 14 | dev | Document why we chose Kafka over SQS. | `adr-writer` | `architecture decision record` | get_skill(adr-writer) | ✅ correct |
| 15 | dev | Turn this support ticket into something engineering can reproduce. | `customer-bug-report` | `support ticket bug reproduction steps` | get_skill(customer-bug-report) | ✅ correct |
| 16 | dev | This test fails randomly in CI. | `test-flake-hunter` | `flaky test` | — | ✅ correct |
| 17 | dev | Our integration tests are nondeterministic. | `test-flake-hunter` | `flaky integration tests nondeterministic` | — | ✅ correct |
| 18 | dev | Draft notes for the new release from the merged PRs. | `release-note-draft` | `release notes` | get_skill(release-note-draft) | ✅ correct |
| 19 | dev | Write up the incident timeline and action items. | `incident-postmortem` | `incident postmortem timeline action items` | — | ✅ correct |
| 20 | dev | Help me with our Kubernetes Helm charts. | `none` | `helm chart kubernetes`; `helm`; `kubernetes` | — | ✅ correct |
| 21 | dev | Translate the marketing page into Spanish. | `none` | — (did not search) | — | ❌ incorrect |
| 22 | dev | Generate PDF invoices for our customers. | `none` | `generate PDF invoices`; `invoice pdf`; `invoice`; `pdf generation` | — | ✅ correct |

Raw trace: [agentic-run-1-baseline.jsonl](agentic-run-1-baseline.jsonl)

### Run 2 — after the fixes, case by case

Console output:

```
### Judge calibration (claude-opus-5-5)

Agreement with hand labels: 86%
- disagreed on: related but wrong skill: judge said correct=False, hallucinated=False

### Agentic discovery (agent claude-haiku-5-5, judge claude-opus-5-5)

| Metric                                                      | dev (22) | holdout (6) | all (28) |
|-------------------------------------------------------------|----------|-------------|----------|
| Agent called `search_skills`                                | 100%     | 100%        | 100%     |
| First search ranked the right skill first (code-graded)     | 100%     | 100%        | 100%     |
| Same, counting only needs where it searched                 | 100%     | 100%        | 100%     |
| Final answer correct (LLM judge)                            | 100%     | 100%        | 100%     |
| Final answer hallucinated a skill or capability (LLM judge) | 0%       | 0%          | 0%       |
| Tool calls per need (mean)                                  | 2.6      | 3.0         | 2.7      |
| Estimated cost                                              | $0.27    | $0.08       | $0.35    |
```

| # | Split | Developer's need | Expected | Searches sent by the agent | Other tools | Judge |
|---|---|---|---|---|---|---|
| 1 | dev | Help me write the release notes for v2.3. | `release-note-draft` | `release notes` | get_skill(release-note-draft) | ✅ correct |
| 2 | dev | What changed since the last tag? I need a changelog entry. | `release-note-draft` | `changelog entry`; `release notes` | get_skill(release-note-draft) | ✅ correct |
| 3 | dev | We just had a production outage, help me write the postmortem. | `incident-postmortem` | `postmortem`; `incident review` | get_skill(incident-postmortem) | ✅ correct |
| 4 | dev | I need an RCA document for yesterday's incident. | `incident-postmortem` | `RCA incident root cause analysis` | get_skill(incident-postmortem), install_skill(incident-postmortem) | ✅ correct |
| 5 | dev | Write a commit message for my staged changes. | `commit-message` | `commit message` | get_skill(commit-message) | ✅ correct |
| 6 | dev | Can you describe this pull request for reviewers? | `pr-description` | `pull request description reviewers` | get_skill(pr-description) | ✅ correct |
| 7 | dev | Is this database migration safe to run in production? | `sql-migration-review` | `database migration safety review production` | get_skill(sql-migration-review) | ✅ correct |
| 8 | dev | Will adding this column lock the Postgres table? | `sql-migration-review` | `postgres migration add column lock`; `database migration review` | get_skill(sql-migration-review) | ✅ correct |
| 9 | dev | My on-call shift ends soon, prepare the handoff. | `oncall-handoff` | `on-call handoff`; `shift handover` | get_skill(oncall-handoff) | ✅ correct |
| 10 | dev | We are seeing a spike of 500s since the last deploy. | `api-error-triage` | `investigate 500 errors spike after deploy`; `incident triage` | get_skill(api-error-triage) | ✅ correct |
| 11 | dev | Review this terraform plan before I apply it. | `terraform-plan-review` | `terraform plan review` | get_skill(terraform-plan-review) | ✅ correct |
| 12 | dev | Does this infra change open a security group or make a bucket public? | `terraform-plan-review` | `infra change review security group public bucket` | get_skill(terraform-plan-review) | ✅ correct |
| 13 | dev | Bump our dependencies without breaking anything. | `dependency-upgrade` | `dependency upgrade bump`; `dependencies update safely` | get_skill(dependency-upgrade) | ✅ correct |
| 14 | dev | Document why we chose Kafka over SQS. | `adr-writer` | `architecture decision record`; `write decision document` | get_skill(adr-writer) | ✅ correct |
| 15 | dev | Turn this support ticket into something engineering can reproduce. | `customer-bug-report` | `support ticket reproduction steps`; `bug report triage` | get_skill(customer-bug-report) | ✅ correct |
| 16 | dev | This test fails randomly in CI. | `test-flake-hunter` | `flaky test investigation`; `CI test failure triage` | get_skill(test-flake-hunter) | ✅ correct |
| 17 | dev | Our integration tests are nondeterministic. | `test-flake-hunter` | `flaky nondeterministic integration tests`; `investigate flaky test` | get_skill(test-flake-hunter) | ✅ correct |
| 18 | dev | Draft notes for the new release from the merged PRs. | `release-note-draft` | `release notes`; `changelog draft from merged PRs` | get_skill(release-note-draft) | ✅ correct |
| 19 | dev | Write up the incident timeline and action items. | `incident-postmortem` | `incident timeline action items postmortem` | get_skill(incident-postmortem) | ✅ correct |
| 20 | dev | Help me with our Kubernetes Helm charts. | `none` | `helm chart kubernetes`; `helm`; `kubernetes` | — | ✅ correct |
| 21 | dev | Translate the marketing page into Spanish. | `none` | `translate marketing page Spanish`; `translation localization` | — | ✅ correct |
| 22 | dev | Generate PDF invoices for our customers. | `none` | `generate PDF invoices`; `invoice` | — | ✅ correct |
| 23 | holdout | Can you prep the PR text for this branch? | `pr-description` | `pull request description PR text`; `PR template draft`; `git branch diff` | get_skill(pr-description), get_skill(pr-description) | ✅ correct |
| 24 | holdout | A test in our nightly build only passes on retry. | `test-flake-hunter` | `flaky test investigation`; `nightly build test retry` | get_skill(test-flake-hunter) | ✅ correct |
| 25 | holdout | Is it safe to drop this column from the orders table? | `sql-migration-review` | `drop column database migration safety`; `schema change review` | get_skill(sql-migration-review) | ✅ correct |
| 26 | holdout | Customers report checkout is failing with 502s. | `api-error-triage` | `investigate 502 errors checkout`; `incident triage` | get_skill(api-error-triage) | ✅ correct |
| 27 | holdout | Write the commit for these changes. | `commit-message` | `commit message` | get_skill(commit-message) | ✅ correct |
| 28 | holdout | Rotate our AWS access keys. | `none` | `rotate AWS access keys`; `AWS credentials rotation` | — | ✅ correct |

Raw trace: [agentic-run-2-after-routing-fix.jsonl](agentic-run-2-after-routing-fix.jsonl)

### Reading run 2 honestly

- One run of a sampled model on 28 needs: one case moves a metric by 4 (dev) to 17 (holdout)
  points.
- A perfect score means the set no longer discriminates; the next step is harder cases.
- The agent installed a skill once without being asked (it is told to offer); a "consent" metric is
  the next code-graded check to add.

### Reproduce

```bash
cp .env.example .env    # set ANTHROPIC_API_KEY
uv run --group eval python -m tests.eval.agentic
uv run python -m tests.eval.trace_report .eval-runs/<newest>.jsonl
```
