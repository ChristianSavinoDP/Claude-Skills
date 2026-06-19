---
name: investigation
description: Produce an investigation deliverable (architecture doc, flow diagram, ADR, runbook, root-cause analysis) following the user's Playbook rules. Use when the ticket is an investigation or the user asks for an analysis/design markdown document rather than code.
---

# Investigation

Procedure for investigation tickets, which produce markdown. The writing rules live in the Playbook under "Investigations"; this skill is the *how*. Apply them, do not restate them. The Playbook's "Shared Standards" apply throughout (concise, no AI slop, verify do not assert, never fabricate).

## Before starting

Per the Playbook's "Investigations > Before Starting":

1. **Ask for the ticket first.**
2. Ask whether a `taskbreakdown.yaml` is needed.
3. Check `docs/investigations/` to match the existing format and style before writing anything new.

## Researching

Per the Playbook's "Never fabricate" and "Verify, do not assert": read the relevant code and docs directly, and track each claim back to evidence you can cite. If context lives in another repo or dependency, search locally, then fetch (GitHub CLI, `go doc`, etc.), then ask. Do not guess.

## Writing

Apply the Playbook's "Investigations > Writing Rules" in full (self-contained, answer every criterion organically, sources at the end, pass markdownlint), plus "No AI slop" (open with the finding, organize by question, no filler). Those are the rules; do not restate them. The procedure on top:

- Organize the document by the question being answered, with real headings a reader can scan; one heading per acceptance criterion or finding.
- State each conclusion plainly with its evidence inline or cited, not hedged.

## Before delivering

Confirm every acceptance criterion is answered and every conclusion is backed by evidence you actually checked (Playbook: "Verify, do not assert"). Diagrams must match the described behavior. Re-read once to cut filler.
