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

Return two separate fenced code blocks so each is easy to copy on its own. Output only these two blocks, with a one-word label before each.

1. **Title.** Format: `<type>(<scope>): [DBI-XXXX] <summary>`.
   - `<type>` is one of `feat`, `fix`, `chore`, `docs` (pick the one that fits the change; if unsure, state your guess).
   - `<scope>` is left for the user to fill: write it literally as `<scope>` so they replace it.
   - `[DBI-XXXX]` uses the real ticket ID.
   - `<summary>` is a concise description of the change, written by you.
   - Example: `feat(<scope>): [DBI-1458] disable auto-generated SDK unit tests`.

2. **Description.** The body, as raw copy-pasteable Markdown following the repo template. Since it contains backticks and code fences, wrap it in a four-backtick fence (````) so the inner content does not break it.
