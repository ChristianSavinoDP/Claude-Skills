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

- **Self-contained:** readable without the ticket.
- **Answer every acceptance-criteria bullet,** presented organically, not as a checklist.
- **Open with the finding,** organized by the question being answered, with real headings a reader can scan (one heading per criterion or finding). No generic intro.
- **Avoid the "term - definition" pattern;** use proper sentences or sections.
- **State each conclusion plainly** with its evidence inline or cited, not hedged.
- **Sources** in a section at the end.
- **Pass markdownlint:** proper heading hierarchy, fenced code blocks with a language, no trailing spaces.
- **In-repo links resolve from the repo root, with a leading slash** (`/internal/jobs/service.go#L53`), because the doc is rendered on GitHub, where a link with no leading slash resolves against the doc's own directory and 404s. A workspace-root-relative path (no slash) is a chat-rendering convention, not GitHub's; translate it. Before writing the first link, confirm the sibling docs' convention with a grep (`grep -rE '\]\(/?[a-z].*\.(go|rb|ya?ml)' docs/investigations`), do not infer it from a sample that happens to have no in-repo links.

## Output

The document itself, nothing around it. Its first line is a markdown heading (`#` or `##`), the first finding or the question being answered: no generic intro, no "here is the investigation", no scope line, no recap of what you read before that heading.

Write it through the Playbook's gated-deliverable flow, so the em-dash, heading-open, and English checks run mechanically before it reaches you as a doc:

1. Write the document to `/tmp/keru-deliverable-investigation-<id>.md` (`<id>` = the ticket key, e.g. `keru-deliverable-investigation-DBI-971.md`). The PreToolUse gate validates it (opens with a heading, no em dashes, English) and DENIES the write if not; fix and Write again until it passes.
2. Once it passes, write the validated content to its real home in the target repo (`docs/investigations/.../investigation.md`, matching the format you checked in "Before starting").
3. Your chat response is a clickable link to the doc plus at most one line (a meta-comment or what to confirm), nothing else. Do not paste the document into chat.

## Before delivering

Confirm every acceptance criterion is answered and every conclusion is backed by evidence you actually checked (Playbook "verify"). Diagrams must match the described behavior. Re-read once to cut filler.

### Adversarial review before delivering

You are blind to your own reasoning: a conclusion you reached feels settled even when its evidence is thin. So before delivering, launch a fresh subagent reviewer over the document, with no stake in what you concluded. Tell it to hunt for what authors miss:

- a conclusion stated without the evidence to back it, or backed by an assumption rather than something checked,
- an acceptance criterion answered only partially or not at all,
- a claim about how the code/system behaves that was inferred, not verified against the source,
- a recommendation that does not follow from the findings.

Give it a second, separate pass on the artifact as it will render, not just its argument: open every in-repo link and confirm it resolves from *this doc's directory on GitHub* (leading-slash root-relative), check anchors and heading hierarchy, and confirm every fenced block declares a language. This pass exists because a content-only review inherits the author's blind spot; a link that names the right code but resolves to a path that does not exist passes every content lens and still 404s.

Then validate each finding against the actual evidence before acting on it: re-read the code or doc and confirm the gap is real, do not accept or dismiss it from assumption (that dismiss-from-memory move is the exact failure this guards against). Fix the confirmed ones, re-verify, then deliver.
