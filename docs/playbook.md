# The Playbook

[`playbook/PLAYBOOK.md`](../playbook/PLAYBOOK.md) holds the always-on rules: language, the first step (get the ticket and its context), verify-don't-assume, shared standards, tool/shell rules, and safety. It is deliberately short. Task-specific procedure (how to review a PR, write code, run an investigation, draft a ticket) lives in the matching skill and loads when that work starts, so the always-on file stays small enough to actually follow.

## Always loaded

The playbook is wired into every context so Claude never works without it:

1. **Any session, any project.** A global `SessionStart` hook in `~/.claude/settings.json` cats `playbook/PLAYBOOK.md` at every session start. The installer generates this hook with the machine's actual repo path (so no absolute path is hardcoded in the committed config) and merges it in; `uninstall.sh` removes it.
2. **Working in this repo.** `CLAUDE.md` at the repo root points at it and is auto-loaded by Claude Code.
3. **Persistent memory.** A memory entry records this repo as the canonical config.

The installer wires all of this automatically; nothing here needs manual setup.

## Rule vs procedure

The playbook holds *always-on rules* (the *what* that applies to every task): stated concisely. Each skill holds both the *procedure* and the *task-specific rules* for one kind of work (PR review rules live in the `pr-review` skill, ticket rules in `writing-tickets`, etc.), loaded only when that work starts. See [skills.md](skills.md).

The split is by scope, not by what-vs-how: if it applies to everything, it is an always-on rule in the playbook; if it only matters for one kind of task, it lives in that task's skill, so the always-on context stays small. A rule lives in exactly one place, never both.

## Editing

Edit `playbook/PLAYBOOK.md` directly. Every consumer reads from it, so there is nothing else to sync. The change applies to all sessions at their next start.

## What not to put in it

- Procedures for a single task (those are skills).
- Anything the codebase already records (structure, history).
- Tool-specific command detail (that lives in the skill that runs the tool).
