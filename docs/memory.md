# Memory vs. the repo

Claude Code keeps a persistent, file-based memory per project, separate from this repo. The harness already defines how memory works (the `user` / `feedback` / `project` / `reference` types, the frontmatter format, the `MEMORY.md` index, and the rule not to duplicate what the code or git history already records). This page does not restate those rules; it states the one boundary they do not: what belongs in memory versus in this repo.

## The line: shared rule vs personal choice

The test is **"does this apply to anyone using the repo, or is it my own choice?"**, not "is it reproducible?".

- **Repo** holds rules that apply to everyone who uses it: the playbook, the skills, the permissions, the hooks. Shared, versioned, public.
- **Memory** holds the user's personal choices and context: who they are, corrections they have given on how to work, and operational choices like which repos to act on.

A whitelisted command is a repo rule (it governs every session, for anyone). A list of repos to triage is a personal choice (this user picked them; another user would pick others). Same shape on disk, different scope, so they live in different places. This is principle #1 ("one source of truth, by scope") applied across the repo/memory boundary, not just within the repo.

## Why the boundary matters

The repo is public and shared. Putting a personal choice in it (a specific repo list, a name, a token-shaped value) either leaks something or forces a choice on everyone who clones it. Putting a shared rule in memory hides it from the repo that is supposed to be the single source of truth, and it stops applying the moment you work on another machine. Keeping each on its correct side is what lets the repo stay authoritative and public while memory stays personal and local.

## Worked example

The `keru-bot-triage` skill triages a set of repos. That set is a personal choice, so it lives in memory (`dependency-bot-repos`), not in the repo: there is no default list committed anywhere. The skill itself (the shared rule: how to triage, read-only, never merge) lives in the repo. The procedure is in [skills.md](skills.md); the split is the point here: behavior in the repo, the user's chosen inputs in memory.

## See also

- [architecture.md](architecture.md): the single-source-of-truth design within the repo.
- [skills.md](skills.md): where task rules live (the repo side of the line).
