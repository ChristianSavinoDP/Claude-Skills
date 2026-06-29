# CLAUDE.md

This repo is the canonical source of truth for how I want Claude to work.

**Always read and apply [`playbook/PLAYBOOK.md`](playbook/PLAYBOOK.md) in full.** It holds the always-on rules: language, the first step (get the ticket and its context), verify-don't-assume, shared standards, tools/shell, and safety. It is short on purpose. Re-read it constantly; the user should never have to remind you of anything written there.

Task-specific rules and procedure (how to review a PR, write code, run an investigation, draft a ticket) live in the matching skill under `skills/`, loaded when that work starts, not in the playbook. Each rule lives in exactly one place: an always-on rule in the playbook, a task rule in its skill, never both.

## Vision and principles

The design decisions in this repo all come from these. When extending it, keep them; if a change fights one of them, it is probably the wrong change.

1. **One source of truth, by scope.** Each rule lives in exactly one place: if it applies to every task, it is in the playbook; if it only matters for one kind of work, it lives in that task's skill. Never both. Docs reference, never restate; and each skill is its own slash command, so there is no wrapper layer to restate it either.
2. **Small always-on context.** The playbook stays short so it is actually followed; if everything is a rule, nothing is. Task detail loads on demand via the skill, so the permanent context is not a wall no one reads.
3. **Less friction, never less safety.** Auto-approve what is safe so work flows, but always stop for what matters. Reducing prompts is a goal; removing a real safety gate is not.
4. **Local vs. remote is the safety line.** Local, reversible work (build, test, edit, format, delete local files) runs without asking. Anything that changes remote state, infrastructure, or data not recoverable from git (deploy, push, apply, DB writes, discarding uncommitted changes) asks first.
5. **Use the right tool, not raw shell.** Files go through Write/Edit (diff, checkpoint, trail); authenticated systems through their CLI (`jira`/`gh`, never WebFetch); parsing through a tool's own flags, not an inline interpreter. Shell is for reading and local, reversible actions.
6. **A deliverable is a gated artifact, not chat prose.** A review, ticket, PR description, or comment-resolution is written to its `/tmp/keru-deliverable-<skill>.md` file, where a PreToolUse gate validates it before it is written and the chat reply is just a link to it. Streamed chat cannot be validated before the user sees it, so the file (not the message) is the deliverable; this is enforced mechanically, not by Claude remembering to.
7. **Verify, do not assert.** Never state something as done or true without checking it. Someone else's claim, a ticket, a PR description is input to verify, not evidence to repeat.
8. **Understand before acting.** A ticket is the start of a chain (linked issues, the originating investigation, related PRs). Read enough of it to know *why* the work is asked before changing anything.
9. **Everything reproducible, nothing hardcoded.** The whole setup is "edit the source, run `scripts/install.sh`". No manual steps, and no machine-specific paths committed to this public repo (the installer resolves them at runtime).

## Working in this repo

This repo is activated on a machine by `scripts/install.sh`: it symlinks skills (each one its own `/keru-*` slash command) into `~/.claude`, syncs `config/` into the global settings, and installs `keru-*` helpers. So the rule when changing anything here is: edit the source (playbook, a skill, `config/`), then re-run `scripts/install.sh`. Editing the installed copy directly is wrong; it is a symlink or a synced block, and the next install overwrites it.

See [docs/architecture.md](docs/architecture.md) for the full design.
