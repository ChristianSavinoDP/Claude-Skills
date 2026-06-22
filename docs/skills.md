# Skills

Skills are procedures Claude runs for a specific kind of task. They live in `skills/<name>/SKILL.md` and are activated by the installer (symlinked into `~/.claude/skills`).

## How a skill triggers

Skills are model-invoked. Each `SKILL.md` has a `description` in its frontmatter, and Claude reads those descriptions to decide, on its own, when a skill applies to your request. You do not call a skill explicitly; you describe what you want, and the matching skill fires.

This makes the `description` the most important line in a skill: it states *when* to use it. A vague description means the skill misfires or never triggers.

```markdown
---
name: pr-review
description: Review a pull request. Use whenever the user asks to review or look at a PR...
---
```

If you want to invoke a flow explicitly instead of relying on the match, use its slash command (see [commands.md](commands.md)). The command is only a shortcut: the playbook ("Load the skill for the task") makes the skill mandatory whenever a request matches it, command or not, so a skill should never be skipped just because you described the task in plain words.

## The explicit-request safeguard

Skill triggering cannot be mechanically forced (Claude Code hooks are reactive; no hook can make the model call a tool). So most of it rests on the playbook and descriptions, which is best-effort. There is one mechanical backstop, for the one verifiable case: if you explicitly say "use the X skill" (or "usá el skill de X") and the turn ends without that skill's `Skill` tool actually being invoked, a `Stop` hook (`keru-require-skill`) blocks the turn from ending and tells Claude to invoke it. It checks the transcript: did a `Skill` call for the requested skill appear after your prompt? It only fires on an explicit "use" instruction, not on casual mentions and not on automatic triggering, so a minor follow-up never gets forced through a skill. It cannot guarantee the retry complies, but it catches the silent skip.

## How skills relate to the playbook

The playbook holds the always-on rules (they apply to every task). A skill holds the procedure AND the task-specific rules for its kind of work, the ones that only matter for that task, so they load on demand instead of bloating the always-on context. A skill applies the playbook's rules but does not restate them; a rule lives in exactly one place, by scope. See [playbook.md](playbook.md).

## Catalogue

| Skill | Triggers when you want to | Notes |
| --- | --- | --- |
| `writing-code` | implement, build, or fix code | reads existing patterns first, stays in scope |
| `pr-review` | review a PR | applies the playbook's review rules |
| `addressing-pr-comments` | resolve review comments | validates each comment before applying |
| `investigation` | produce a doc, ADR, runbook, or RCA | markdown deliverable, sources at the end |
| `pr-description` | write a PR description | follows the repo's PR template |
| `writing-tickets` | draft a ticket | output in chat only, never a file |
| `gather-context` | gather context from a ticket, PR, repo, or URL | read-only; resolves the chain both ways, can read uncloned repos |

## Authoring a new skill

1. Create `skills/<name>/SKILL.md` with `name` and `description` frontmatter.
2. Write the procedure and the task-specific rules. Apply the playbook's always-on rules; do not restate them.
3. Run `scripts/install.sh` to symlink it.
4. Restart to pick it up.

Pick a name that does not collide with built-in commands (`review`, `code-review`). If it collides, yours wins but it is confusing; prefer a distinct name.
