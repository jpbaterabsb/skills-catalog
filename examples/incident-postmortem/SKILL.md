---
name: incident-postmortem
description: Writes a blameless incident postmortem in the team's format (summary, impact, timeline, root cause, action items). Use when the user asks to write, draft or prepare a postmortem, post-incident review, incident report or RCA after an outage or production incident.
---

# Incident postmortem

Produce a blameless postmortem draft that the incident owner can review and share.

## Steps

1. Collect the facts before writing. Ask for whatever the user has not given: what broke, when it
   started and ended (with timezone), who was affected and how, how it was detected, and what
   fixed it. Use logs, chat exports or notes the user points to; never guess times or numbers.
2. Copy `templates/postmortem.md` and fill every section in order.
3. **Impact** must be measurable: duration, number or share of users or requests affected,
   revenue or SLA impact if known. Write "unknown" rather than estimating.
4. **Timeline**: one line per event, `HH:MM TZ — what happened`, from first signal to resolution.
   Mark detection, escalation, mitigation and resolution explicitly.
5. **Root cause**: ask "why" until you reach a cause in the system (process, tooling, design),
   not a person. Separate the trigger from the underlying cause.
6. **Action items**: each one has an owner, a due date and a type (prevent, detect, mitigate).
   Prefer few concrete items over many vague ones.
7. Re-read the draft for blame: rewrite any sentence that names a person as the cause.

## Rules

- Blameless: describe what people did and why it made sense at the time, never who is at fault.
- Mark anything uncertain with `<!-- verify: ... -->` for the incident owner.
