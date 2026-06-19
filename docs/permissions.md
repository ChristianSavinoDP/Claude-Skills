# Permissions and Hooks

How this repo reduces permission prompts without giving up safety. All of it lives in `config/` and is merged into the global `~/.claude/settings.json` by the installer.

## The model

Two things decide whether a tool call prompts you:

1. **Explicit rules** (`allow` / `ask` / `deny`): lists of concrete commands. Precedence is `deny` > `ask` > `allow`.
2. **`defaultMode`**: what happens to anything that matches no rule.

The rules win over `defaultMode`. So an `ask` rule still prompts even when the default mode would auto-run.

## defaultMode: acceptEdits

`acceptEdits` auto-accepts file edits (Edit/Write) and common filesystem commands (`mkdir`, `mv`, `cp`) without prompting. It does **not** auto-run arbitrary Bash; anything not in `allow` still prompts. This is the balance point: no friction editing files, but a brake on commands. (Editing files under `.claude/` is auto-accepted via an `Edit(.claude/**)` allow rule; Claude Code otherwise protects that directory.)

(`dontAsk` does not auto-accept edits, and `bypassPermissions` skips almost every prompt including on other repos. `acceptEdits` is the deliberate middle.)

## allow: runs silently

Read-only and local, reversible commands, so they never prompt:

- Navigation / read: `cd`, `ls`, `pwd`, `cat`, `grep`, `rg`, `find`, `head`, `tail`, `which`, `sed`, `awk`
- Filesystem: `mkdir`, `mv`, `cp`, `touch`, `echo`, and `rm` (deleting local files is reversible via git)
- Git reads: `status`, `diff`, `log`, `branch`, `fetch`
- Build/test/lint per language: Go (`build`, `test`, `vet`, `fmt`, `mod tidy`, ...), Node (`npm test/ci`, `eslint`, `prettier`, `tsc`, ...), Gradle, Python (`pytest`, `ruff`, ...), .NET
- Terraform read-only: `plan`, `validate`, `version`, `init`, `fmt`
- Jira / GitHub reads: `jira issue view/list`, `jira epic list`, `jira me`, `gh pr view/diff/list/checks`, `gh run view/list`, `gh workflow view/list`, `gh api repos/*`
- The `keru-jira-dev` helper

`make`, `mise`, and `go tool` are deliberately NOT in allow; they go through a hook (below).

## ask: always prompts

Destructive actions (per the playbook's definition), so they prompt even under `acceptEdits`:

- `git commit`, `git push`
- Discarding uncommitted work: `git reset --hard`, `git checkout -- <files>`, `git restore`, `git clean`
- `terraform apply`, `terraform destroy`
- Jira writes: `issue create/move/assign/comment/edit`, `epic add/create`, `sprint`
- GitHub writes / CI triggers: `pr create/merge/review/comment/close/edit`, `run rerun/cancel`, `workflow run/enable/disable`

## The make / mise / go tool hook

`make`, `mise`, and `go tool` are not in allow, because a target name hides what it does: `make deploy` could run `terraform apply`. A static allow rule would also nullify the guard, since an `allow` match short-circuits a hook's `ask`. So instead, a `PreToolUse` agent hook is the only thing that evaluates them.

Before one of these runs, the hook reads the Makefile / mise config / go.mod tool, resolves what it actually executes, and:

- forces a confirmation prompt (`permissionDecision: ask`) if it is destructive per the playbook (deploy, terraform apply/destroy, DB mutations, network mutations, ...);
- lets it run silently if it only builds, tests, lints, formats, generates, or deletes local files;
- defaults to asking if it cannot tell.

Trade-off: it adds a few seconds to each `make`/`mise`/`go tool` call. That is the cost of a real safety net over those wrappers.

## The read-only pipeline hook

Allow rules match each subcommand of a compound command independently, so a read-only exploration like `cd x && grep ... | grep -v ...` can still prompt when one piece does not cleanly match. A second `PreToolUse` hook (`keru-safe-read`, a fast deterministic script, not an agent) handles that: it parses the command with shell-aware tokenizing (handling pipelines, loops, conditionals, safe redirections like `2>/dev/null`, and command substitution whose contents are themselves read-only) and auto-approves it only if every segment is a known read-only command (`grep`, `find`, `sed`, `awk`, `cat`, `ls`, `git log/diff/status`, `go list/env`, `gh` read subcommands, `base64`, ...) with no dangerous flags (`-i`, `-exec`, `-delete`), no file redirection, and no arbitrary interpreter (`python3 -c`, `ruby -e`). Anything it cannot prove safe it leaves alone, deferring to the normal allow/ask flow. It never blocks.

## Changing it

Edit `config/permissions.json` or `config/hooks.json`, then re-run `scripts/install.sh`. The installer syncs: it tracks the rules and hooks it manages (under a `_keruManaged` marker in the settings), so each run adds what is new and removes what you dropped from config, while leaving rules you added elsewhere untouched (including the playbook's `SessionStart` hook). Changes apply to new sessions.
