# Permissions and Hooks

How this repo reduces permission prompts without giving up safety. All of it lives in `config/` and is merged into the global `~/.claude/settings.json` by the installer.

## The model

Two things decide whether a tool call prompts you:

1. **Explicit rules** (`allow` / `ask` / `deny`): lists of concrete commands. Precedence is `deny` > `ask` > `allow`.
2. **`defaultMode`**: what happens to anything that matches no rule.

The rules win over `defaultMode`. So an `ask` rule still prompts even when the default mode would auto-run.

## defaultMode: acceptEdits

`acceptEdits` auto-accepts file edits (Edit/Write) and common filesystem commands (`mkdir`, `mv`, `cp`) without prompting. It does **not** auto-run arbitrary Bash; anything not in `allow` still prompts. This is the balance point: no friction editing files, but a brake on commands.

(`dontAsk` does not auto-accept edits, and `bypassPermissions` skips almost every prompt including on other repos. `acceptEdits` is the deliberate middle.)

## allow: runs silently

Read-only and safe commands, so they never prompt:

- Navigation / read: `ls`, `pwd`, `cat`, `grep`, `rg`, `find`, `head`, `tail`, `which`
- Filesystem: `mkdir`, `mv`, `cp`, `touch`, `echo`
- Git reads: `status`, `diff`, `log`, `branch`, `fetch`
- Terraform read-only: `plan`, `validate`, `version`, `init` (none of these apply infrastructure changes)
- Task runners: `make`, `mise` (guarded by a hook, see below)
- Jira / GitHub reads: `jira issue view`, `jira epic list`, `jira me`, `gh pr view`, `gh pr checks`, `gh run view/list`, `gh workflow view/list`

## ask: always prompts

State-changing commands, so they prompt even under `acceptEdits`:

- `git commit`, `git push`, `git reset --hard`
- `terraform apply`, `terraform destroy`, `rm -rf`
- Jira writes: `issue create/move/assign/comment/edit`, `epic add/create`, `sprint`
- GitHub writes / CI triggers: `pr create/merge/review/comment/close/edit`, `run rerun/cancel`, `workflow run/enable/disable`

## The make/mise hook

`make *` and `mise *` are allowed broadly, but a target name hides what it does: `make deploy` could run `terraform apply`. A `PreToolUse` agent hook closes that gap.

Before a `make`/`mise` command runs, the hook reads the Makefile or mise config, resolves what the target actually executes, and:

- forces a confirmation prompt (`permissionDecision: ask`) if it finds something destructive (deploy, terraform apply/destroy, db drops, `rm -rf`, `git push`, ...);
- lets it run silently if it only builds, tests, lints, or stays local;
- defaults to asking if it cannot tell.

Trade-off: it adds a few seconds to each `make`/`mise` call. That is the cost of keeping those allow rules broad with a real safety net.

## Changing it

Edit `config/permissions.json` or `config/hooks.json`, then re-run `scripts/install.sh`. The installer syncs: it tracks the rules and hooks it manages (under a `_keruManaged` marker in the settings), so each run adds what is new and removes what you dropped from config, while leaving rules you added elsewhere untouched (including the playbook's `SessionStart` hook). Changes apply to new sessions.
