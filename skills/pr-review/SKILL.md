---
name: pr-review
description: Review a pull request following the user's Playbook review rules. Use when the user asks to review a PR, look at a PR, or check changes on a branch before merge. Covers both code and investigation PRs.
---

# PR Review

Procedure for reviewing a PR. The review *rules* (tone, comment categories, decision flow, what not to do) live in the Playbook under "PR Reviews"; this skill is the *how*. Do not restate the rules here, apply them.

## Before reviewing

1. **Ask for the ticket first.** Per the Playbook's mandatory first step, do not fetch the diff or analyze anything until you have the ticket. The ticket sets the work type (feature vs follow-up vs investigation) and acceptance criteria, which change how you review.
2. Identify the PR: ask for the PR number/URL if not given.

## Gather context

- Fetch the diff and metadata with the GitHub CLI: `gh pr view <pr>` and `gh pr diff <pr>`.
- For an investigation PR, also check `docs/investigations/` for the expected format.
- Read the changed files in full, not just the diff hunks, when behavior depends on surrounding code.

## Review

Walk the diff file by file. Apply the Playbook's "PR Reviews" section:

- Run the Playbook checklist (acceptance criteria, compile/test failures, callers updated, test coverage, evidence for investigations).
- Classify each finding as blocking, nit, or question, per the Playbook.
- Use the Playbook's decision flow to decide whether each observation is worth a comment.
- Scope rules differ by ticket type (follow-up: resolve everything here; feature: refactors valid). Confirm the type from the ticket.

## Output

- Use the Playbook's comment format: file path with line reference, code block, then the suggestion.
- Frame as suggestions, not imperatives.
- If everything is good, just approve. Do not comment to show you reviewed it.

## Posting (only if asked)

If the user wants comments posted rather than drafted in chat, confirm first, then use `gh pr review` / `gh pr comment`. Default to drafting in chat.
