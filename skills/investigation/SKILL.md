---
name: investigation
description: Produce an investigation deliverable (architecture doc, flow diagram, ADR, runbook, root-cause analysis) following the user's Playbook rules. Use when the ticket is an investigation or the user asks for an analysis/design markdown document rather than code.
---

# Investigation

Procedure for investigation tickets, which produce markdown. The writing rules (self-contained, answer every acceptance criterion organically, sources at the end, pass markdownlint) live in the Playbook under "Investigations"; this skill is the *how*. Apply them, do not restate them.

## Before starting

Per the Playbook's "Investigations > Before Starting":

1. **Ask for the ticket first.**
2. Ask whether a `taskbreakdown.yaml` is needed.
3. Check `docs/investigations/` to match the existing format and style before writing anything new.

## Researching

- Read the relevant code and docs directly. Never fabricate APIs, signatures, or behavior, per the Playbook's "Never fabricate" rule. If context lives in another repo or dependency, search locally, then fetch (GitHub CLI, `go doc`, etc.), then ask. Do not guess.
- Track each claim back to evidence you can cite.

## Writing

Apply the Playbook's "Investigations > Writing Rules":

- Self-contained: readable without the ticket.
- Answer every acceptance-criteria bullet, presented organically, not as a checklist.
- Avoid the "term - definition" pattern; use proper sentences or sections.
- Put sources in a section at the end.
- Pass markdownlint: proper heading hierarchy, fenced code blocks with a language, no trailing spaces.

## Before delivering

Confirm every acceptance criterion is answered and every conclusion is backed by evidence. Diagrams must match the described behavior.
