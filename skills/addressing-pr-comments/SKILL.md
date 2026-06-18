---
name: addressing-pr-comments
description: Resolve review comments on a PR following the user's Playbook rules. Use when the user got review feedback and wants help responding to or fixing PR comments, or asks to address review comments.
---

# Addressing PR Comments

Procedure for working through review comments. The rules (validate first, push back when warranted, fix root cause, do not over-correct) live in the Playbook under "Addressing PR Comments"; this skill is the *how*. Apply the rules, do not restate them.

## Before changing anything

1. **Ask for the ticket first**, per the Playbook's mandatory first step. Scope is defined by the ticket type.
2. Pull the comments: `gh pr view <pr> --comments`, and the diff for context: `gh pr diff <pr>`.

## For each comment

Follow the Playbook's "Addressing PR Comments" section:

- **Validate first.** Decide whether the comment is correct and in scope before writing code. Not every comment deserves a change.
- **Push back when warranted.** If a comment is wrong or out of scope, draft a respectful reply explaining why instead of applying it.
- **Fix the root cause**, not a band-aid that just silences the comment.
- **Group related comments** that point at the same underlying issue.
- **Do not over-correct.** Change what was asked, nothing more.

## Output

For each comment, state: apply or push back, the reasoning, and the concrete change or the drafted reply. Keep replies in the Playbook's suggestion tone.
