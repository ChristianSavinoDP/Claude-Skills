---
name: keru-investigation
description: Produce an investigation deliverable (architecture doc, flow diagram, ADR, runbook, root-cause analysis). Use whenever the ticket is an investigation or the user asks to investigate, analyze, research, or document a design/decision in markdown rather than write code, with or without a slash command. Expects a Jira ticket key or link.
---

# Investigation

Procedure for investigation tickets, which produce markdown. The Playbook's always-on rules apply (verify, never fabricate, concise, no slop); this skill adds the investigation rules.

## Before starting

1. Get the ticket first (Playbook "first step"). Use the `keru-gather-context` skill to gather it and its full chain (read-only), including any linked investigation's PR and document. Do not start until that skill's gate passes.
2. Ask whether a `taskbreakdown.yaml` is needed.
3. Check `docs/investigations/` to match the existing format and style before writing anything new.

## Researching

Read the relevant code and docs directly; track each claim back to evidence you can cite. If context lives in another repo or dependency, search locally, then fetch (gh, `go doc`), then ask. Never guess (Playbook "never fabricate", "verify").

## Writing rules

- **Self-contained:** readable without the ticket. The body cites code and repo artifacts only. A person's name or a quoted ticket/PR comment never appears: those are input that told you *what* to investigate, not evidence for the deliverable, which states conclusions on code you checked. When a comment raised an open question, restate the question on its own terms (no name, no quote) and answer it from the code; who raised it is irrelevant to a reader of the doc.
- **Answer every acceptance-criteria bullet,** presented organically, not as a checklist.
- **Open with the finding,** organized by the question being answered, with real headings a reader can scan (one heading per criterion or finding). No generic intro.
- **Avoid the "term - definition" pattern;** use proper sentences or sections.
- **State each conclusion plainly** with its evidence inline or cited, not hedged.
- **Derive each field's design implications, not just its name and type.** For a schema-shaped subject, a field is not only a label: a per-entry key (e.g. a `country` alongside a group id) changes identity, uniqueness, sort order, and hashing; a narrowed enum changes what the diff can distinguish. Ask "what does this field change about the behavior I am describing?" for each one and state that implication, not only the field's existence. A conclusion that names the fields correctly but never derives what they imply is the half-answer a reviewer sends back.
- **Sources** in a section at the end.

Form, verification, and placement are not this skill's job: the `keru-writing-docs` skill owns them, so the markdownlint, in-repo-link, em-dash, and claim-verification rules live there, not restated here. This skill decides WHAT the doc says and its structure; writing-docs guarantees it is correct and well-formed and writes it to its home.

## Output

The document itself, nothing around it. Its first line is a markdown heading (`#` or `##`), the first finding or the question being answered: no generic intro, no "here is the investigation", no scope line, no recap of what you read before that heading.

When the draft is ready, hand it to the `keru-writing-docs` skill (mode `investigation`) to verify, form, gate, and place it. Pass it:

- the drafted document,
- its home: `docs/investigations/.../investigation.md`, matching the format you checked in "Before starting",
- the sources every claim must be verified against (the code and repo artifacts you researched),
- the ticket key as the id.

writing-docs runs the verification (never assuming, always against the source that would disprove the claim), confirms this skill's writing rules are met (every acceptance criterion answered, self-contained with no names, any diagram matching the behavior it depicts, any recommendation following from the findings), enforces the form rules through the gated-deliverable flow (`/tmp/keru-deliverable-investigation-<id>.md`), and writes the doc to its home. Your chat response is its link plus at most one line (a meta-comment or what to confirm), nothing else; do not paste the document into chat.
