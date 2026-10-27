"""Discovery eval data: a realistic team catalog and the needs developers bring to it.

Skills are deliberately close to each other (release notes vs. commit messages vs. pull request
descriptions, postmortems vs. on-call handoffs vs. error triage), so ranking matters. Each case has
the ``need`` as a developer would say it and the ``query`` an assistant would plausibly send to
``search_skills`` after reformulating it into key terms (what the tool description asks for).
``expected`` is the skill that should come first, or None when nothing in the catalog fits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

# name -> description. The two real examples are read from disk so the eval tracks them.
EXTRA_SKILLS = {
    "commit-message": (
        "Writes Conventional Commits messages from staged changes. Use when the user asks for a "
        "commit message or to commit their work."
    ),
    "pr-description": (
        "Drafts a pull request title and description (summary, motivation, testing, risks) from "
        "a branch diff. Use when opening or updating a pull request."
    ),
    "sql-migration-review": (
        "Reviews SQL schema migrations for locking, downtime and rollback risks on PostgreSQL. "
        "Use before merging a database migration."
    ),
    "oncall-handoff": (
        "Summarizes open alerts, ongoing incidents and pending follow-ups into an on-call handoff "
        "note at the end of a shift."
    ),
    "api-error-triage": (
        "Triages HTTP 5xx error spikes in a service: finds the failing endpoint, correlates with "
        "recent deploys and logs, and proposes a mitigation."
    ),
    "terraform-plan-review": (
        "Reviews a Terraform plan for destructive changes, drift and security issues such as "
        "public buckets or open security groups before apply."
    ),
    "dependency-upgrade": (
        "Upgrades a project's dependencies safely: reads changelogs for breaking changes, updates "
        "lockfiles and runs the test suite."
    ),
    "adr-writer": (
        "Writes an Architecture Decision Record (context, decision, alternatives, consequences) "
        "for a technical decision."
    ),
    "customer-bug-report": (
        "Turns a customer support ticket into a reproducible bug report with steps, expected and "
        "actual behavior, and environment."
    ),
    "test-flake-hunter": (
        "Investigates flaky tests: reruns them, finds nondeterminism (time, ordering, shared "
        "state) and proposes a fix."
    ),
}


# Short but complete instructions, so an agent that reads a skill with get_skill sees a usable
# procedure. (The first live agentic run used a generic placeholder body, and the agent rightly
# declined to recommend a skill that looked like a stub.)
SKILL_BODIES = {
    "commit-message": """# Commit message

1. Run `git diff --staged` and read every hunk; ignore unstaged changes.
2. Pick the type: feat, fix, refactor, test, docs, chore, build, perf.
3. Subject: `type(scope): imperative summary`, lowercase, no period, at most 72 characters.
4. Body, when the change is not obvious: why it was needed and any trade-off, wrapped at 72.
5. One logical change per commit: if the diff mixes concerns, propose how to split it.
""",
    "pr-description": """# Pull request description

1. Read `git log main..HEAD` and the full diff of the branch.
2. Title: what changes for users or callers, not how.
3. Sections: Summary, Motivation, Changes, Testing (commands run and results), Risks and rollback.
4. Link the issue and call out anything reviewers must look at closely.
""",
    "sql-migration-review": """# SQL migration review (PostgreSQL)

1. For each statement, state the lock it takes (e.g. ACCESS EXCLUSIVE for most ALTER TABLE).
2. Flag table rewrites: column type changes, volatile defaults, adding NOT NULL without a check.
3. Require `CREATE INDEX CONCURRENTLY` and `lock_timeout` on large or hot tables.
4. Check there is a rollback path and that application code tolerates both schemas mid-deploy.
5. Verdict: safe, safe with changes (list them), or unsafe (explain).
""",
    "oncall-handoff": """# On-call handoff

1. List open alerts with status, owner and next check time.
2. Summarize ongoing incidents: impact, current mitigation, what is being watched.
3. List follow-ups promised during the shift, with owners and due dates.
4. Note risky deploys or maintenance planned for the next shift.
5. End with "Needs attention first:" and at most three items.
""",
    "api-error-triage": """# API 5xx triage

1. Find which endpoints and status codes spiked, and when the spike started.
2. Correlate with deploys, config changes and dependency incidents around that time.
3. Read error logs and traces for the top failing endpoint; quote the dominant error.
4. Propose the fastest safe mitigation (rollback, feature flag, scale up) before root cause.
5. Hand over to the incident-postmortem skill once mitigated.
""",
    "terraform-plan-review": """# Terraform plan review

1. Run or read `terraform plan`; list every destroy and replace first.
2. Flag security issues: public buckets, 0.0.0.0/0 ingress, wildcard IAM, unencrypted storage.
3. Flag drift: resources changed outside Terraform that this apply would revert.
4. Check state and provider version changes.
5. Verdict: safe to apply, apply with changes, or do not apply (explain).
""",
    "dependency-upgrade": """# Dependency upgrade

1. List outdated dependencies and group them: patch, minor, major.
2. For each major upgrade, read the changelog and list breaking changes that affect this code.
3. Upgrade one group at a time, update the lockfile, and run the full test suite after each.
4. Fix or pin anything that breaks, and summarize what changed and what was deferred.
""",
    "adr-writer": """# Architecture Decision Record

1. Title: the decision, as a short noun phrase. Status: proposed or accepted.
2. Context: the forces and constraints, without arguing for an option yet.
3. Decision: what was chosen, in one paragraph.
4. Alternatives: each option considered and why it was not chosen.
5. Consequences: what becomes easier, what becomes harder, and what to revisit later.
""",
    "customer-bug-report": """# Customer bug report

1. Extract what the customer did, what they expected and what happened, in their words.
2. Turn it into numbered reproduction steps; mark any step you had to assume.
3. Record environment: plan, browser or client version, region, account id, time of the report.
4. Attach evidence (screenshots, request ids) and state severity and number of customers affected.
""",
    "test-flake-hunter": """# Flaky test investigation

1. Rerun the test in isolation and in the full suite, at least 20 times each; record failures.
2. Look for time dependence, ordering between tests, shared state, randomness and network calls.
3. Reproduce deterministically (fixed seed, frozen clock, reversed order) before fixing.
4. Fix the cause; quarantine with an issue link only if the fix must wait.
""",
}


@dataclass(frozen=True)
class Case:
    need: str
    query: str
    expected: str | None
    # "dev" cases may inform changes to tool descriptions; "holdout" cases were written before the
    # first such change and must never be used to tune them, so they show whether a change
    # generalizes or only fixes the cases it was tuned on.
    split: str = "dev"


CASES = [
    Case("Help me write the release notes for v2.3.", "release notes", "release-note-draft"),
    Case(
        "What changed since the last tag? I need a changelog entry.",
        "changelog entry release",
        "release-note-draft",
    ),
    Case(
        "We just had a production outage, help me write the postmortem.",
        "postmortem outage",
        "incident-postmortem",
    ),
    Case(
        "I need an RCA document for yesterday's incident.",
        "incident report root cause",
        "incident-postmortem",
    ),
    Case("Write a commit message for my staged changes.", "commit message", "commit-message"),
    Case(
        "Can you describe this pull request for reviewers?",
        "pull request description",
        "pr-description",
    ),
    Case(
        "Is this database migration safe to run in production?",
        "database migration review",
        "sql-migration-review",
    ),
    Case(
        "Will adding this column lock the Postgres table?",
        "postgres schema locking",
        "sql-migration-review",
    ),
    Case(
        "My on-call shift ends soon, prepare the handoff.",
        "on-call shift handoff",
        "oncall-handoff",
    ),
    Case(
        "We are seeing a spike of 500s since the last deploy.",
        "5xx errors spike deploy",
        "api-error-triage",
    ),
    Case(
        "Review this terraform plan before I apply it.",
        "terraform plan review",
        "terraform-plan-review",
    ),
    Case(
        "Does this infra change open a security group or make a bucket public?",
        "security group public bucket",
        "terraform-plan-review",
    ),
    Case(
        "Bump our dependencies without breaking anything.",
        "upgrade dependencies breaking changes",
        "dependency-upgrade",
    ),
    Case("Document why we chose Kafka over SQS.", "architecture decision record", "adr-writer"),
    Case(
        "Turn this support ticket into something engineering can reproduce.",
        "customer ticket bug report",
        "customer-bug-report",
    ),
    Case("This test fails randomly in CI.", "flaky test", "test-flake-hunter"),
    Case(
        "Our integration tests are nondeterministic.", "nondeterministic tests", "test-flake-hunter"
    ),
    Case(
        "Draft notes for the new release from the merged PRs.",
        "release notes merged pull requests",
        "release-note-draft",
    ),
    Case(
        "Write up the incident timeline and action items.",
        "incident timeline action items",
        "incident-postmortem",
    ),
    Case("Help me with our Kubernetes Helm charts.", "kubernetes helm chart", None),
    Case("Translate the marketing page into Spanish.", "translate marketing spanish", None),
    Case("Generate PDF invoices for our customers.", "invoice pdf generation", None),
    # Held out: written before the first tool-description change; never tune against these.
    Case(
        "Can you prep the PR text for this branch?",
        "pull request description",
        "pr-description",
        "holdout",
    ),
    Case(
        "A test in our nightly build only passes on retry.",
        "flaky test retry",
        "test-flake-hunter",
        "holdout",
    ),
    Case(
        "Is it safe to drop this column from the orders table?",
        "schema migration locking",
        "sql-migration-review",
        "holdout",
    ),
    Case(
        "Customers report checkout is failing with 502s.",
        "5xx errors spike",
        "api-error-triage",
        "holdout",
    ),
    Case("Write the commit for these changes.", "commit message", "commit-message", "holdout"),
    Case("Rotate our AWS access keys.", "rotate aws access keys", None, "holdout"),
]
