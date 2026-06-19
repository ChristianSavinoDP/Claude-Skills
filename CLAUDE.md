# CLAUDE.md

This repo is the canonical source of truth for how I want Claude to work.

**Always read and apply [`playbook/PLAYBOOK.md`](playbook/PLAYBOOK.md) in full.** It governs language, standards, code, PR descriptions, reviews, investigations, and tickets. Re-read it constantly; the user should never have to remind you of anything written there.

`playbook/PLAYBOOK.md` is the single source of truth. Do not duplicate its rules elsewhere; point to it.

## Vision and principles

The design decisions in this repo all come from these. When extending it, keep them; if a change fights one of them, it is probably the wrong change.

1. **One source of truth, enforced.** Every rule and every output format lives in exactly one place (the playbook); skills, commands, and docs reference it, never restate it. The repo applies this to itself: a change is made in one spot, not synced across copies.
2. **Rule vs. procedure.** The playbook holds the *what* (always-on principles); skills hold the *how* (the steps to execute a task). A skill never re-lists a playbook rule; it links to it and adds only the procedure.
3. **Less friction, never less safety.** Auto-approve what is safe so work flows, but always stop for what matters. Reducing prompts is a goal; removing a real safety gate is not.
4. **Local vs. remote is the safety line.** Local, reversible work (build, test, edit, format, delete local files) runs without asking. Anything that changes remote state, infrastructure, or data not recoverable from git (deploy, push, apply, DB writes, discarding uncommitted changes) asks first.
5. **Use the right tool, not raw shell.** Files go through Write/Edit (diff, checkpoint, trail); authenticated systems through their CLI (`jira`/`gh`, never WebFetch); parsing through a tool's own flags, never `python3 -c`. Shell is for reading and local, reversible actions.
6. **Verify, do not assert.** Never state something as done or true without checking it. Someone else's claim, a ticket, a PR description is input to verify, not evidence to repeat.
7. **Understand before acting.** A ticket is the start of a chain (linked issues, the originating investigation, related PRs). Read enough of it to know *why* the work is asked before changing anything.
8. **Everything reproducible, nothing hardcoded.** The whole setup is "edit the source, run `scripts/install.sh`". No manual steps, and no machine-specific paths committed to this public repo (the installer resolves them at runtime).

## Working in this repo

This repo is activated on a machine by `scripts/install.sh`: it symlinks skills and commands into `~/.claude`, syncs `config/` into the global settings, and installs `keru-*` helpers. So the rule when changing anything here is: edit the source (playbook, a skill, a command, `config/`), then re-run `scripts/install.sh`. Editing the installed copy directly is wrong; it is a symlink or a synced block, and the next install overwrites it.

See [docs/architecture.md](docs/architecture.md) for the full design.
