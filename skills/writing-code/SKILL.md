---
name: writing-code
description: Implement a code change following the user's Playbook rules. Use when the ticket asks to build, implement, fix, or change code (not review, not investigate, not docs).
---

# Writing Code

Procedure for implementing a code change. The rules (DRY, comments only when warranted, tests only if requested, clean related cruft now instead of leaving a follow-up) live in the Playbook under "Writing Code" and "Shared Standards"; apply them, do not restate them.

## Before coding

1. **Ask for the ticket first**, per the Playbook's mandatory first step. Scope and acceptance criteria come from it.
2. **Read before writing.** Review the surrounding code and existing patterns so the change matches what is already there (Playbook: "Follow existing patterns", "DRY"). Reuse what exists instead of adding new.

## While coding

Apply the Playbook's "Writing Code" and "Shared Standards" sections in full: stay in scope but clean related cruft now, reuse existing packages and follow the reference code's reusable shape, no needless comments, never fabricate APIs, tests only if asked, write file contents with Write/Edit (not `cat >`), and never discard uncommitted work on your own. Those are the rules; do not restate them.

The procedure on top of those rules:

- Match the file's existing naming, style, and idioms (read a neighbor before writing).
- If a revert or discard comes up, show the branch state (`git status`, `git log`, `git diff`) and wait for the user to say what to revert; do not choose what to discard yourself.

## Before delivering

Review every changed line: nil safety, error handling, unused imports, correct types and field names, missing returns. Re-read the relevant code once more if unsure. Confirm the change satisfies the acceptance criteria and nothing beyond them.

Do not end by offering to commit or push the change (see the Playbook's "Never offer to commit or push"). Stop after the work is done; the user will ask if they want a commit.
