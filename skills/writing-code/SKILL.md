---
name: writing-code
description: Implement a code change following the user's Playbook rules. Use when the ticket asks to build, implement, fix, or change code (not review, not investigate, not docs).
---

# Writing Code

Procedure for implementing a code change. The rules (DRY, comments only when warranted, tests only if requested, refactors beyond scope go to a follow-up) live in the Playbook under "Writing Code" and "Shared Standards"; apply them, do not restate them.

## Before coding

1. **Ask for the ticket first**, per the Playbook's mandatory first step. Scope and acceptance criteria come from it.
2. **Read before writing.** Review the surrounding code and existing patterns so the change matches what is already there (Playbook: "Follow existing patterns", "DRY"). Reuse what exists instead of adding new.

## While coding

Apply the Playbook:

- Stay within the ticket scope. Refactors beyond it go to a follow-up ticket, except trivially small changes.
- No comments unless the "why" is non-obvious.
- Match the file's naming, style, and idioms.
- Never fabricate APIs or signatures: verify against the codebase or fetch the source. Do not guess.
- Tests only if the ticket or user asks; when writing them, each test covers a distinct behavior, no redundancy.

## Before delivering

Review every changed line: nil safety, error handling, unused imports, correct types and field names, missing returns. Re-read the relevant code once more if unsure. Confirm the change satisfies the acceptance criteria and nothing beyond them.
