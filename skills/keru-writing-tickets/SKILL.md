---
name: keru-writing-tickets
description: Draft a ticket (feature, bug, investigation, follow-up, task breakdown). Use whenever the user asks to write, draft, or create a ticket/issue/story, with or without a slash command. Output goes in chat, never to a file.
---

# Writing Tickets

Procedure for drafting tickets. The Playbook's rules apply (concise, no slop, never fabricate); this adds the ticket-specific ones.

## Before drafting

- **Know the type (gate):** feature, bug, investigation, follow-up, or task breakdown. If the user did not say, ask and wait, do not guess. Ruling a type out is not picking one. The type shapes the content.
- **Draft in chat only,** never a file. Do not create it in Jira or offer to: the output is the draft in chat, the user takes it from there.

## A ticket is what + why, not how

The implementer decides how. Length is a defect: a reader should grasp the whole ticket in one scan.

- **Title:** one line, the outcome. Not sub-tasks joined by "and".
- **Context:** 2 to 4 sentences (problem + why). Link the source ticket/investigation, do not restate it.
- **Each criterion is one checkable line,** an observable outcome. No file/function names, `if`/flag values, or per-bullet rationale; state an essential constraint as an outcome ("X no longer runs when Y is unchanged"), not as code.
- **Past ~6 to 7 criteria it is probably several tickets:** split, do not grow one.
- Add value with sharper criteria, not more words: flag a missing criterion or an unstated assumption.

For a bug, give observed vs expected in the paragraph. An investigation's criteria are the questions to answer, not a solution. A task breakdown lists sub-tickets, each one line with short criteria.

## Output

Write this to `/tmp/keru-deliverable-writing-tickets-<id>.md` first, where `<id>` is the related ticket key when there is one (parent/epic/source), else a short slug (the Playbook's gated-deliverable rule, so one draft does not overwrite another); your chat reply is a link to that file plus at most one line, not its pasted contents. The file has this shape and nothing else (note the size):

```text
**Align companion's PR CI with the partner-integrations twin**

companion runs its heavy CI jobs on every PR and still auto-commits generated files. DBI-1461 fixed most of it but missed the terraform/ci gating, the api-gen and sre auto-commits, templ, and the aggregate check. Mirror the partner-integrations setup; the missed cases and rationale live in DBI-1461.

### Acceptance Criteria

- The terraform and ci jobs run only when path-filters reports their paths changed.
- The api-gen and sre jobs fail on a diff instead of auto-committing, and run read-only.
- A templ format check runs and fails on a diff.
- No auto-commit action remains under the PR workflows.
- A single aggregate "check" job reports the combined status of every PR job.
- A docs-only PR skips terraform and ci while "check" still reports green.
```
