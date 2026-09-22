---
description: Collect the keru artifacts kept under the Claude config dir: the ticket-chain context snapshots (default older than 7 days) and the gated deliverable drafts (default older than 30). Always confirms against an audit list first. A snapshot rebuilds itself on demand; a deliverable does not, so the list is shown before anything is removed.
disable-model-invocation: true
---

# Artifacts Prune

Keep `~/.claude/keru-context/` and `~/.claude/keru-deliverables/` from growing forever. `disable-model-invocation: true` means this never fires on its own; it runs only when the user types `/keru-artifacts-prune`, which is the intent to delete.

These directories exist because `/tmp` did not survive a reboot on this machine, so the artifacts moved somewhere durable. The cost of durable is that nothing collects them anymore, and this is that collector.

## Scope

Two kinds, two default windows, because they are not the same thing:

- **Context snapshots** (`~/.claude/keru-context/<KEY>.md`), default **7 days**: a cache. `keru-context-snapshot write <KEY>` rebuilds one with no model at all, so losing it costs a few Jira reads.
- **Gated deliverables** (`~/.claude/keru-deliverables/keru-deliverable-*.md`), default **30 days**: model work (a review, a ticket, a PR description) that does not come back. Anything still wanted belongs in Jira, in a PR, or in a repo, not here.

Age is **mtime**, when the file was last written. For a snapshot that means last *verified*, because `keru-context-snapshot check` touches the file when it reports `current`, so a ticket still being worked keeps its snapshot alive. Access time is deliberately not used: on this volume a read refreshes `atime` only while `atime` is still older than `mtime`, so every read after the first leaves it frozen and an `-atime` test would guard nothing. `find -mtime +N` also cuts on the day after N, so the effective retention is a day longer than the window says.

Nothing outside those two directories is touched, and only `.md` files in them are considered.

## Procedure

1. Get the audit, do not blindly prune: run `keru-artifacts-prune audit` (read-only, auto-approved). Add `--days=N` to override both windows or `--kind=context|deliverables` to restrict to one kind, matching what the user asked for.
2. Show the plan: per kind, the directory, its window, and each candidate with its age and size, plus how many files stay. Call out the deliverables explicitly, by name: each one is model work that will not regenerate. Ask for explicit confirmation. Typing the command is the intent; the confirmation is against a concrete list.
3. On confirmation, run `keru-artifacts-prune prune` with the same flags. It deletes exactly the audited set and reports what was removed and what failed.
4. Report per kind: what was removed, anything that **failed** (named, so the user can look), and what remains. For a removed snapshot, note that the next run of the ticket's work rebuilds it via `keru-context-snapshot write`.

The audit-then-confirm step is the safety line, and it matters more here than for a cache purge: a deleted deliverable is not recoverable by re-running anything. The remote is never touched.
