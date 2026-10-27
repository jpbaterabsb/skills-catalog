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


@dataclass(frozen=True)
class Case:
    need: str
    query: str
    expected: str | None


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
]
