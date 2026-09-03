---
name: keru-writing-docs
description: Finalize a markdown doc so it is correct, verified, and well-formed, then write it to its real home in the repo. The shared guarantee step that keru-writing-code (a doc shipped with a code change) and keru-investigation (an analysis doc) hand off to: it verifies every factual claim against the source that would disprove it (it never assumes), enforces the Playbook's form rules (no em dashes, English, markdownlint, render-correctness), and places the file. Also use directly to author or finalize repo documentation whose content is known: a README, a runbook, an access or reference doc. Not for doing the analysis or the code change itself (those are keru-investigation and keru-writing-code); this skill guarantees and places the doc they produce.
---

# Writing Docs

The guarantee layer for any markdown doc that lands in a repo. A caller brings the content and its intent (keru-writing-code for a doc shipped with a change, keru-investigation for an analysis doc, or you directly); this skill makes that content **correct** (every claim verified against its source, never assumed), **well-formed** (em dashes, English, markdownlint, render-correctness), and **written to its real home**. The Playbook's always-on rules apply (verify, never fabricate, concise, no slop); this skill adds the doc-guarantee procedure.

The one rule that does not bend, in either mode: **the reviewer never assumes, it verifies.** What changes between a simple companion doc and a heavy investigation is the doc's depth and structure, never the rigor of verification.

## Inputs (from the caller)

State these when you invoke this skill; they are how writing-code and investigation parameterize it.

- **The content, or its intent, and the draft if there is one.** What the doc must say.
- **The mode:** `companion` (a doc shipped alongside a code or infra change, usually short and factual) or `investigation` (an analysis deliverable, deeper and structured). The mode selects the gate contract and the structural checks, never the verification bar.
- **The home:** the exact path the doc lives at in the repo (e.g. `.../access.<consumer>.dlq.md`, or `docs/investigations/.../investigation.md`).
- **The context to verify against:** the sources every claim must be checked against (the sibling docs, the precedent's real implementation, the ACL or config file the change edits, the schema, the partition keys). Not a summary of them, the sources themselves, so verification opens them rather than trusting the draft.
- **The id:** the ticket key or PR number, for the gated draft filename.

## Verify first: the reviewer never assumes

Before writing anything to the repo, verify the draft against its sources. You are blind to a claim you wrote, so fan out fresh subagent reviewers over the draft (Playbook "Parallelize the work", the fan-out shape), with no stake in how it was written. Three lenses, dispatched as separate subagents in one message (they inherit different blind spots, so never collapse them into one):

- **Claims against the source that would disprove them.** For every factual statement the doc makes about the system (a schema, a header or key contract, what a grant or ACL allows, what a precedent does, a partition key, a cadence), open the source that would DISPROVE it, not the one that inspired it. A plausible framing ("replay routes a message back to its source topic") reads as settled while the file under the cursor (the ACL that grants WRITE to one source, not three) contradicts it. A claim the draft makes that no source was opened for is an assumption, and an assumption is the exact failure this skill exists to stop. Check the draft against ITSELF too: prose that names three sources while its own table lists two is catchable here with no external source at all. Two sharpenings of "open the source": for a schema-shaped claim (fields, enum values, keys), enumerate the actual set from the source field by field rather than paraphrasing a remembered subset, since a doc that lists most fields but silently drops two, or narrows an enum to the values you recall, is wrong in a way that reads complete; and an unmerged or in-flight source is not a source of record, so re-open the current source (the merged one, if it landed) and re-verify each claim drawn from it at every delivery, not once, and if it merged since the last pass, diff what changed, because names, types, and keys move at merge.
- **Literal fidelity.** For every value the doc quotes from a source (a retention, a partition count, a channel handle, a metric name, a line number, a command), re-open the source and confirm the token matches exactly, including non-ASCII punctuation, at the byte level when a character is ambiguous.
- **Rendered artifact.** Open every in-repo link and confirm it resolves from THIS doc's directory on GitHub (root-relative, leading slash, e.g. `/internal/x.go#L10`); confirm heading hierarchy, anchors, and that every fenced block declares a language.

Mode adds one thing to the claims lens, never a discount on it:

- **`companion`:** confirm the doc documents only behavior that exists and is verified, and defers not-yet-built behavior to its downstream ticket rather than describing it speculatively. A short, factual doc has almost no surface to get wrong; prefer it.
- **`investigation`:** confirm the investigation skill's own writing rules are met: every acceptance criterion answered, the body self-contained (no names, no quoted comments), any diagram matching the behavior it depicts, and any recommendation following from the findings.

When the subagents return, **validate each finding against the actual source yourself before acting on it:** re-open the file and confirm the gap is real, do not accept or dismiss it from assumption (that dismiss-from-memory move is the exact failure this guards against). Fix the confirmed ones, re-verify, then place it.

## Write and place it

Once the content is verified, write it through the Playbook's gated-deliverable flow, so the em-dash, English, and markdown-render checks run mechanically before it lands:

1. Write the doc to `/tmp/keru-deliverable-<token>-<id>.md`, where `<token>` is `doc` in companion mode or `investigation` in investigation mode, and `<id>` is the ticket key or PR number (e.g. `/tmp/keru-deliverable-doc-DBI-1676.md`). The PreToolUse gate validates it (opens with a heading or a bold title, no em dashes, English, well-formed markdown) and DENIES the write if not; fix and Write again until it passes.
2. Beyond the gate's render check, satisfy the target repo's markdownlint: proper heading hierarchy, fenced blocks with a language, no trailing spaces. If the repo has a markdownlint config and the tool is available, run it against the draft and fix what it flags; confirm the sibling docs' in-repo link convention with a grep before trusting a sample.
3. Once it passes, write the validated content to its real home (the path the caller gave), matching the format of the sibling docs there.
4. Your response for this doc is a clickable link to the placed file (or the gated draft) plus at most one line, nothing else. Do not paste the document into chat.
