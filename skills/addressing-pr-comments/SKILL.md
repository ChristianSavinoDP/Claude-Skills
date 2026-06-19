---
name: addressing-pr-comments
description: Resolve review comments on a PR following the user's Playbook rules. Use when the user got review feedback and wants help responding to or fixing PR comments, or asks to address review comments.
---

# Addressing PR Comments

Procedure for working through review comments. The rules (validate first, push back when warranted, fix root cause, do not over-correct) live in the Playbook under "Addressing PR Comments"; this skill is the *how*. Apply the rules, do not restate them. The Playbook's "Shared Standards" apply throughout (concise, no AI slop, never fabricate).

## Before changing anything

1. **Ask for the ticket first**, per the Playbook's mandatory first step. Scope is defined by the ticket type.
2. Pull the comments: `gh pr view <pr> --comments`, and the diff for context: `gh pr diff <pr>`.

## For each comment

Apply the Playbook's "Addressing PR Comments" section in full (validate first, push back when warranted in the rebuttal tone, fix the root cause, group related comments, do not over-correct). Those are the rules; do not restate them. Work through the comments one at a time, deciding apply-or-push-back for each before touching code.

## Output

Per the Playbook's "Addressing PR Comments" output rules. Do not restate them here.
