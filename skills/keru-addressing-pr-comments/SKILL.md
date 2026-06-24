---
name: keru-addressing-pr-comments
description: Resolve review comments on a PR. Use whenever the user brings PR review feedback (from a person or Copilot), pastes review comments, or asks to address/respond to/fix them, even without a slash command. Trigger on pasted comments or "Copilot said...", "the reviewer wants...", "handle these comments". Expects a GitHub PR link.
---

# Addressing PR Comments

Procedure for working through review comments. The Playbook's always-on rules apply (verify, fix root cause, concise); this skill adds the rules for handling comments.

## Steps

1. Get the ticket first (Playbook "first step"); scope is defined by the ticket type. Use the `keru-gather-context` skill to gather the PR and its linked ticket and chain (read-only) before deciding on any comment.
2. Pull the comments (`gh pr view <pr> --comments`) and the diff for context (`gh pr diff <pr>`).
3. Work through the comments one at a time, deciding apply-or-push-back for each before touching code.

## Rules

- **Validate first.** Evaluate whether each comment is correct and in scope before writing code. Verify it against the codebase, do not dismiss from memory (a wrong dismissal is the common failure). Not every comment deserves a change.
- **Push back when warranted,** directly: if a comment is wrong or out of scope, say why, respectful, concise, factual, not hedged as a suggestion. You are defending your own PR, not reviewing someone else's.
- **Fix the root cause,** not a band-aid that silences the comment.
- **Group related comments** that point at the same underlying issue.
- **Do not over-correct.** Change what was asked, nothing more.

## Output

One block per comment, no intro or summary around them. For each: apply or push back, the reasoning in a sentence, and the concrete change or the drafted reply. A reply meant to be posted goes in its own copy-pasteable fenced block. Posting on the PR is a state change: confirm first, read-only by default.
