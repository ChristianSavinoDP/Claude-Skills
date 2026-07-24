# Skills

Skills are procedures Claude runs for a specific kind of task. They live in `skills/<name>/SKILL.md` and are activated by the installer (symlinked into `~/.claude/skills`).

## How a skill triggers

Skills are model-invoked. Each `SKILL.md` has a `description` in its frontmatter, and Claude reads those descriptions to decide, on its own, when a skill applies to your request. You do not call a skill explicitly; you describe what you want, and the matching skill fires.

This makes the `description` the most important line in a skill: it states *when* to use it. A vague description means the skill misfires or never triggers.

```markdown
---
name: keru-pr-review
description: Review a pull request. Use whenever the user asks to review or look at a PR...
---
```

## Invoking a skill explicitly

Every skill is also a slash command: type `/keru-<name>` to run it deliberately, with arguments (`/keru-writing-code DBI-1458`). Claude Code merged custom commands into skills, so a skill IS its command; there is no separate wrapper file. The slash name comes from the skill's directory name, which is why every skill here is named `keru-*`: it keeps them grouped and easy to spot in the `/` menu, distinct from built-in and plugin commands. Whatever you type after the name is available to the skill as `$ARGUMENTS`.

**Typed-only actions live under `commands/`.** An action that changes state and must never auto-trigger (whether it mutates remote infra or does something local but irreversible) does not live in `skills/`; it lives in `commands/` as a native command file, `commands/keru-<name>.md`. It still appears as `/keru-<name>` and runs when you type it, and carries `disable-model-invocation: true` in its frontmatter so Claude never invokes it on its own from a matching request. The separate directory is the point: it makes the "typed-only, state-changing, never auto-fired" line visible in the layout rather than hidden in a per-skill flag. See the [Commands](#commands) section below.

The command is only a shortcut: the playbook ("Load the skill for the task") makes the skill mandatory whenever a request matches it, typed or not, so a skill is never skipped just because you described the task in plain words. Commands are the deliberate exception: they are typed on purpose, never triggered by a matching description.

## The explicit-request safeguard

Skill triggering cannot be mechanically forced (Claude Code hooks are reactive; no hook can make the model call a tool). So most of it rests on the playbook and descriptions, which is best-effort. There is one mechanical backstop, for the one verifiable case: if you explicitly say "use the X skill" (or "usá el skill de X") and the turn ends without that skill's `Skill` tool actually being invoked, a `Stop` hook (`keru-require-skill`) blocks the turn from ending and tells Claude to invoke it. It checks the transcript: did a `Skill` call for the requested skill appear after your prompt? It only fires on an explicit "use" instruction, not on casual mentions and not on automatic triggering, so a minor follow-up never gets forced through a skill. It cannot guarantee the retry complies, but it catches the silent skip.

## How skills relate to the playbook

The playbook holds the always-on rules (they apply to every task). A skill holds the procedure AND the task-specific rules for its kind of work, the ones that only matter for that task, so they load on demand instead of bloating the always-on context. A skill applies the playbook's rules but does not restate them; a rule lives in exactly one place, by scope. See [playbook.md](playbook.md).

## Catalogue

Each skill is also its slash command (type the name, or just describe the task and let it trigger).

| Skill | Triggers when you want to | Notes |
| --- | --- | --- |
| `keru-writing-code` | implement, build, or fix code | reads existing patterns first, stays in scope |
| `keru-pr-review` | review a PR | applies the playbook's review rules |
| `keru-addressing-pr-comments` | resolve review comments | validates each comment before applying |
| `keru-investigation` | produce a doc, ADR, runbook, or RCA | markdown deliverable, sources at the end |
| `keru-pr-description` | write a PR description | follows the repo's PR template |
| `keru-writing-tickets` | draft a ticket | gated deliverable; drafts only, never creates it in Jira |
| `keru-gather-context` | gather context from a ticket, PR, repo, or URL | read-only; resolves the chain both ways, can read uncloned repos |
| `keru-bot-triage` | triage dependency/security bot PRs and Dependabot alerts across repos | read-only; uses the `keru-bot-triage` helper, never merges |
| `keru-datadog-audit` | audit DataDog errors for a set of services | read-only via `pup`; gated deliverable, groups by recurrence and attributes (ours vs external, reading repos locally), then offers to route to `keru-debugging` (cause in doubt) or `keru-writing-tickets` (recurring + ours) on the user's yes |
| `keru-debugging` | find why a specific thing fails | validates the root cause with evidence; diagnoses only, does not write the fix; also called by other skills |
| `keru-responding-to-ci` | get a PR's failing CI green | triages each red check, then calls debugging/writing-code; read-only on CI, never reruns or pushes |
| `keru-branch-audit` | list stale local branches (gone upstream) across the projects root or one named repo | read-only; uses the `keru-branch-cleanup` helper |
| `keru-repo-audit` | show what switching to default + fast-forwarding would do, per repo | read-only; uses the `keru-repo-update` helper |

The read-only audit halves (`keru-branch-audit`, `keru-repo-audit`) are skills: they only inspect, so triggering on a matching request is fine. Their state-changing counterparts are commands (below).

## Commands

Commands live in `commands/` as native Claude Code command files (one flat `keru-<name>.md` each), symlinked by the installer into `~/.claude/commands/`. They are `/keru-<name>` like skills, but are **typed-only**: each carries `disable-model-invocation: true`, so Claude never fires one from a matching request. They are separated from skills because they all share one trait: they **change state and must not auto-fire**, whether the change is remote (infra) or local but irreversible (deleting branches, moving working trees off their current commit). Every command confirms against a concrete plan before it acts.

| Command | Triggers when you type it, to | Notes |
| --- | --- | --- |
| `keru-branch-clean` | delete stale local branches across the projects root or one named repo | typed-only; confirms against an audit list first, skips current + default. Local but irreversible (deleted branches are not git-recoverable) |
| `keru-repo-update` | switch each repo to its default branch and fast-forward to origin | typed-only; confirms against an audit first, stashes tracked changes, `--ff-only`, skips diverged. Local; recoverable but changes many working trees at once |
| `keru-terraform-apply` | run a terraform change from local through the `dp` CLI | typed-only; asks the env first, previews with an unlocked `-target` plan, confirms before apply, never applies to prod. Mutates remote infra |
| `keru-create-ticket` | create one or more tickets in Jira | typed-only; drafts each with `keru-writing-tickets`, asks board/type/service, adds `BAU` when there is no epic, confirms before each `jira issue create`. Writes to Jira |
| `keru-pr-handle` | open a PR (or move an existing one forward) | typed-only; creates from `keru-pr-description` after guarding branch + clean tree, else routes to `addressing-pr-comments`/`responding-to-ci` or confirms a merge. Pushes, creates, merges |
| `keru-review-publish` | run a PR review and post it to GitHub | typed-only; runs `keru-pr-review`, validates each inline comment anchors to a modified line, posts one review with the verdict's event. Publishes a review |

## Authoring a new skill or command

For a skill (a task flow that may trigger on a matching request):

1. Create `skills/keru-<name>/SKILL.md` with `name` and `description` frontmatter (set `name` to match the directory, `keru-<name>`). The directory name is what you type after `/`, so the `keru-` prefix is what groups these in the menu.
2. Write the procedure and the task-specific rules. Apply the playbook's always-on rules; do not restate them.
3. Run `scripts/install.sh` to symlink it.
4. Restart to pick it up.

For a command (a typed-only, state-changing action): create `commands/keru-<name>.md` instead, a flat file with `description` and `disable-model-invocation: true` frontmatter (no `name` key: the command name comes from the filename). Same install/restart. Reach for a command, not a skill, whenever the action changes state and must not fire on its own.

The `keru-` prefix also keeps names clear of built-in and plugin commands (`review`, `code-review`); a bare name like `review` would collide, and although your skill wins, it is confusing.
