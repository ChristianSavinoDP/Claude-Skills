---
name: pr-description
description: Write a PR description following the user's Playbook rules and the repo's PR template. Use when the user asks to write, draft, or fill in a pull request description.
---

# PR Description

Procedure for writing a PR description. The rules live in the Playbook under "PR Descriptions"; apply them, do not restate them.

## Steps

1. **Ask for the ticket first**, per the Playbook's mandatory first step. You need the JIRA ID and the acceptance criteria.
2. **Read the repo's template:** `.github/PULL_REQUEST_TEMPLATE.md`. Fill in its sections; do not invent your own structure. If there is no template, keep it minimal: what changed, and how to test if relevant.
3. **Inspect the actual changes:** `gh pr diff <pr>` or `git diff`. Describe the real code changes, not the theory.

## Filling it in

Per the Playbook's "PR Descriptions":

- Replace the `DBI-XXXX` placeholder with the real ticket ID.
- "What Changed" describes the actual code, concisely.
- "How to Test" only if there are meaningful manual steps (new endpoints, UI, specific scenarios). If it is purely internal logic covered by automated tests, write "Covered by unit/integration tests" or remove the section. Do not fabricate test steps.

## Output

Return the finished description as raw, copy-pasteable Markdown, not rendered prose. Put the whole thing in a single fenced code block so the user can copy it straight into GitHub. Since the description itself contains backticks and code fences, wrap it in a four-backtick fence (````) so the inner content does not break it. Output only that block, nothing after it.
