# Skills

Skills are procedures Claude runs for a specific kind of task. They live in `skills/<name>/SKILL.md` and are activated by the installer (symlinked into `~/.claude/skills`).

## How a skill triggers

Skills are model-invoked. Each `SKILL.md` has a `description` in its frontmatter, and Claude reads those descriptions to decide, on its own, when a skill applies to your request. You do not call a skill explicitly; you describe what you want, and the matching skill fires.

This makes the `description` the most important line in a skill: it states *when* to use it. A vague description means the skill misfires or never triggers.

```markdown
---
name: pr-review
description: Review a pull request following the user's Playbook review rules. Use when the user asks to review a PR...
---
```

If you want to invoke a flow explicitly instead of relying on the match, use its slash command (see [commands.md](commands.md)).

## How skills relate to the playbook

A skill carries the *how* (the procedure: which commands to run, what order, the output shape). It defers the *what* (the rules) to [`playbook/PLAYBOOK.md`](../playbook/PLAYBOOK.md). A skill references the playbook rather than restating it, so a rule lives in exactly one place. See [playbook.md](playbook.md).

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
2. Write the procedure. Reference playbook rules; do not copy them.
3. Run `scripts/install.sh` to symlink it.
4. Restart to pick it up.

Pick a name that does not collide with built-in commands (`review`, `code-review`). If it collides, yours wins but it is confusing; prefer a distinct name.
