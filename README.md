# Claude-Skills

A guide to working with Claude the way I want: a short playbook of always-on rules, a set of task flows (skills) that carry the rules and steps for each kind of work, and a setup that loads them into every session. This repo is the single source of truth.

## Set up once

```bash
scripts/install.sh
```

That wires the repo into Claude Code (skills, which double as `/keru-*` commands, permissions, the playbook) and checks the `gh` and `jira` tools. Restart Claude Code afterward. Full steps and tool login in [docs/getting-started.md](docs/getting-started.md).

## Using it day to day

You rarely think about the pieces; you just describe the task. The right flow fires on its own, or you invoke it with a slash command.

**Start from a ticket or a PR.** Hand Claude a Jira key, a Jira URL, or a GitHub PR link and it gathers the full context first: the ticket, its linked issues, the investigation that created it, and the related PRs, reading other repos remotely if needed. Then it does the work.

```text
read DBI-1458
/keru-writing-code DBI-1458
/keru-pr-review https://github.com/dailypay/partner-integrations/pull/619
```

**Common flows** (type the command, or just describe it and the skill triggers):

| You want to | Command | Give it |
| --- | --- | --- |
| Implement a change | `/keru-writing-code` | a ticket |
| Review a PR | `/keru-pr-review` | a PR link |
| Resolve review comments | `/keru-addressing-pr-comments` | a PR link |
| Write a PR description | `/keru-pr-description` | a PR link |
| Run an investigation | `/keru-investigation` | a ticket |
| Draft a ticket | `/keru-writing-tickets` | a short description |
| Just gather context | `/keru-gather-context` | a key, URL, PR, or repo |
| Triage dependency/security bots | `/keru-bot-triage` | nothing, or `owner/repo`s |

**What is safe.** Read commands and local file edits run without prompting. State-changing actions always ask first: `git commit`/`push`, `terraform apply`, PR merges, ticket writes, and discarding uncommitted work (`git reset --hard`, `checkout --`, `restore`, `clean`). `make`, `mise`, and `go tool` are inspected by a hook before running, so a hidden destructive target prompts you. Jira and GitHub always go through the `jira`/`gh` CLIs; a hook blocks WebFetch to those domains. Details in [docs/permissions.md](docs/permissions.md).

## Changing how Claude works

Edit an always-on rule in [`playbook/PLAYBOOK.md`](playbook/PLAYBOOK.md); edit a task's rules or steps in its skill under `skills/`; then re-run `scripts/install.sh`. There is nothing else to sync: every consumer reads from this repo. Why it is built this way is in [docs/architecture.md](docs/architecture.md).

## Learn more

- [getting-started.md](docs/getting-started.md): install, tool login, verify.
- [playbook.md](docs/playbook.md): the rules, and how they load into every session.
- [skills.md](docs/skills.md): how skills trigger, how to invoke them as `/keru-*`, and the catalogue.
- [permissions.md](docs/permissions.md): the permission model and the hooks (make/mise/go-tool guard, read-only pipeline, WebFetch block).
- [external-tools.md](docs/external-tools.md): `gh` and `jira` setup, and how context is gathered.
- [architecture.md](docs/architecture.md): the single-source-of-truth design.
- [memory.md](docs/memory.md): what belongs in memory vs. in the repo.
