# The Playbook

[`playbook/PLAYBOOK.md`](../playbook/PLAYBOOK.md) is the single source of truth for how Claude should work: language, shared standards, writing code, PR descriptions, reviews, investigations, and tickets.

## Always loaded

The playbook is wired into every context so Claude never works without it:

1. **Any session, any project.** A global `SessionStart` hook in `~/.claude/settings.json` cats `playbook/PLAYBOOK.md` at every session start. The installer generates this hook with the machine's actual repo path (so no absolute path is hardcoded in the committed config) and merges it in; `uninstall.sh` removes it.
2. **Working in this repo.** `CLAUDE.md` at the repo root points at it and is auto-loaded by Claude Code.
3. **Persistent memory.** A memory entry records this repo as the canonical config.

The installer wires all of this automatically; nothing here needs manual setup.

## Rule vs procedure

The playbook holds *rules* (the *what*): always-on principles, stated concisely. Skills hold *procedures* (the *how*): how to execute a task, loaded only when relevant. A skill references a playbook rule instead of copying it, so each rule lives in exactly one place. See [skills.md](skills.md).

This is why most things belong in the playbook, not in a skill: if it is a principle that should apply to every response, it is a rule. If it is the step-by-step for one task, it is a procedure.

## Editing

Edit `playbook/PLAYBOOK.md` directly. Every consumer reads from it, so there is nothing else to sync. The change applies to all sessions at their next start.

## What not to put in it

- Procedures for a single task (those are skills).
- Anything the codebase already records (structure, history).
- Tool-specific command detail (that lives in the skill that runs the tool).
