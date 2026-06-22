---
name: pr-description
description: Write a pull request description following the repo's PR template. Use whenever the user asks to write, draft, fill in, or update a PR description or PR body, with or without a slash command.
---

# PR Description

Procedure for writing a PR description. The Playbook's always-on rules apply (verify, concise, no slop); this skill adds the PR-description rules.

## Steps

1. Get the ticket first (Playbook "first step"): you need the JIRA ID and acceptance criteria.
2. Read the repo's template `.github/PULL_REQUEST_TEMPLATE.md` and fill in its sections. Do not invent your own structure. No template: keep it minimal (what changed, how to test if relevant).
3. Inspect the actual changes (`gh pr diff <pr>` or `git diff`). Describe the real code, not the theory.

## Rules

- Replace the `DBI-XXXX` placeholder with the real ticket ID.
- "What Changed": the actual code changes, concisely.
- "How to Test": only if there are meaningful manual steps (new endpoints, UI, specific scenarios). Purely internal logic covered by automated tests: write "Covered by unit/integration tests" or remove the section. Do not fabricate test steps.

## Output

Two copy-pasteable blocks, nothing else:

1. **Title**, format `<type>(<scope>): [DBI-XXXX] <summary>`. `<type>` is `feat`/`fix`/`chore`/`docs`. Leave `<scope>` literally as `<scope>` for the user to fill. Real ticket ID. Example: `feat(<scope>): [DBI-1458] disable auto-generated SDK unit tests`.
2. **Body**, the description following the repo template, in a four-backtick fence so its inner backticks do not break it.

Output only those two blocks. Do not offer to commit afterward.
