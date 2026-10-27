---
name: release-note-draft
description: Drafts release notes for a new version from merged pull requests and commit messages. Use when the user asks to write, prepare or summarize release notes or a changelog entry for a release.
---

# Release note draft

Produce a first draft of release notes that a maintainer can edit and publish.

## Steps

1. Find the range to describe. Ask for the previous and the new version (or tag) if the user did
   not give them, then list the changes with `git log --oneline <previous>..<new>`.
2. Read the subject (and body, when the subject is unclear) of each commit or merged pull request.
   Skip merge commits, version bumps and changes that only touch CI or formatting.
3. Group every remaining change under exactly one heading of the template in
   `templates/release-notes.md`: **Highlights**, **Breaking changes**, **Features**, **Fixes**,
   **Internal**. Omit headings that end up empty.
4. Rewrite each entry for users, not for reviewers: say what changed and why it matters, in one
   sentence, in the past tense. Keep pull request numbers as references, e.g. `(#123)`.
5. Put anything that requires users to act (config changes, removed flags, migrations) under
   **Breaking changes**, and explain the action to take.
6. Fill in the version and date at the top and return the draft as Markdown.

## Rules

- Never invent changes that are not in the history.
- If a change is ambiguous, keep it and add `<!-- check: ... -->` for the maintainer.
