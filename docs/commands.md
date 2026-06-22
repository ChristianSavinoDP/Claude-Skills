# Commands

Commands are slash commands you invoke explicitly by typing `/<name>` in the chat. They live in `commands/*.md` and are activated by the installer (symlinked into `~/.claude/commands`).

## Skill vs command

Both run the same flows; the difference is who triggers them.

| | Triggered by | Use when |
| --- | --- | --- |
| **Skill** | Claude, when your request matches its `description` | you describe a task and want the right flow to fire on its own |
| **Command** | you, by typing `/keru-name` | you want to invoke a flow deliberately, with arguments |

The command is optional. The skill is supposed to fire on a plain-language request that matches it; the command just makes it explicit and lets you pass arguments. If a task matches a skill, the skill applies whether or not you used the command (see the playbook's "Load the skill for the task").

## How the commands here are built

Each command is a thin wrapper that invokes its matching skill with `$ARGUMENTS`. It does not duplicate the skill's procedure or the playbook's rules; it just points at the skill and states the expected input. This keeps a single source of truth: edit the skill, and both the skill trigger and the command pick up the change.

```markdown
---
description: Review a pull request following the Playbook (invokes the pr-review skill).
---

Review the pull request: $ARGUMENTS

Expects a GitHub PR link...
```

`$ARGUMENTS` is whatever you type after the command name.

## What each command expects

Several commands chain through `gather-context` first to gather read-only context, which also satisfies the playbook's "get the ticket first" and "follow the chain" rules.

All commands are prefixed `keru-` so they are easy to spot in the `/` menu.

| Command | Pass it | Flow |
| --- | --- | --- |
| `/keru-pr-review` | a GitHub PR link | gather-context (PR + linked ticket + chain) then pr-review |
| `/keru-addressing-pr-comments` | a GitHub PR link | gather-context then addressing-pr-comments |
| `/keru-pr-description` | a GitHub PR link | gather-context (PR + ticket) then pr-description |
| `/keru-investigation` | a Jira key or link | gather-context then investigation |
| `/keru-writing-code` | a Jira key or link | gather-context then writing-code |
| `/keru-writing-tickets` | a short description | writing-tickets (creates, does not consume) |
| `/keru-gather-context` | a key, Jira/epic URL, PR link, or repo/file | gather-context (read-only) |

## Examples

```text
/keru-pr-review https://github.com/dailypay/dailypay-typescript-sdk/pull/97
/keru-writing-code DBI-1458
/keru-gather-context https://dailypay.atlassian.net/browse/DBI-1458
```

## A note on markdownlint

Command files are prompts, not documents: everything below the frontmatter is sent to the model. They intentionally have no top-level heading, so they trip MD041. That warning is expected here; adding a heading would inject noise into the prompt.
