---
name: pr-description
description: Write a PR description following the user's Playbook rules and the repo's PR template. Use when the user asks to write, draft, or fill in a pull request description.
---

# PR Description

Procedure for writing a PR description. The rules live in the Playbook under "PR Descriptions"; apply them, do not restate them. The Playbook's "Shared Standards" apply throughout (concise, no AI slop, verify do not assert, never fabricate).

## Steps

1. **Ask for the ticket first**, per the Playbook's mandatory first step. You need the JIRA ID and the acceptance criteria.
2. **Read the repo's template:** `.github/PULL_REQUEST_TEMPLATE.md`. Fill in its sections; do not invent your own structure. If there is no template, keep it minimal: what changed, and how to test if relevant.
3. **Inspect the actual changes:** `gh pr diff <pr>` or `git diff`. Describe the real code changes, not the theory.

## Filling it in

Apply the Playbook's "PR Descriptions" section in full (real ticket ID, describe the actual code concisely, "How to Test" only when there are meaningful manual steps). Those are the rules; do not restate them. Base the content on the real diff you inspected, not the theory.

## Output

Per the Playbook's "PR Descriptions" format (title block + copy-pasteable body block). Do not restate it here.
