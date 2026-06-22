---
name: investigation
description: Produce an investigation deliverable (architecture doc, flow diagram, ADR, runbook, root-cause analysis). Use whenever the ticket is an investigation or the user asks to investigate, analyze, research, or document a design/decision in markdown rather than write code, with or without a slash command.
---

# Investigation

Procedure for investigation tickets, which produce markdown. The Playbook's always-on rules apply (verify, never fabricate, concise, no slop); this skill adds the investigation rules.

## Before starting

1. Get the ticket first (Playbook "first step").
2. Ask whether a `taskbreakdown.yaml` is needed.
3. Check `docs/investigations/` to match the existing format and style before writing anything new.

## Researching

Read the relevant code and docs directly; track each claim back to evidence you can cite. If context lives in another repo or dependency, search locally, then fetch (gh, `go doc`), then ask. Never guess (Playbook "never fabricate", "verify").

## Writing rules

- **Self-contained:** readable without the ticket.
- **Answer every acceptance-criteria bullet,** presented organically, not as a checklist.
- **Open with the finding,** organized by the question being answered, with real headings a reader can scan (one heading per criterion or finding). No generic intro.
- **Avoid the "term - definition" pattern;** use proper sentences or sections.
- **State each conclusion plainly** with its evidence inline or cited, not hedged.
- **Sources** in a section at the end.
- **Pass markdownlint:** proper heading hierarchy, fenced code blocks with a language, no trailing spaces.

## Before delivering

Confirm every acceptance criterion is answered and every conclusion is backed by evidence you actually checked (Playbook "verify"). Diagrams must match the described behavior. Re-read once to cut filler.

### Adversarial review before delivering

You are blind to your own reasoning: a conclusion you reached feels settled even when its evidence is thin. So before delivering, launch a fresh subagent reviewer over the document, with no stake in what you concluded. Tell it to hunt for what authors miss:

- a conclusion stated without the evidence to back it, or backed by an assumption rather than something checked,
- an acceptance criterion answered only partially or not at all,
- a claim about how the code/system behaves that was inferred, not verified against the source,
- a recommendation that does not follow from the findings.

Then validate each finding against the actual evidence before acting on it: re-read the code or doc and confirm the gap is real, do not accept or dismiss it from assumption (that dismiss-from-memory move is the exact failure this guards against). Fix the confirmed ones, re-verify, then deliver.
