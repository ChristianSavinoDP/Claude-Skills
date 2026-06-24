# Permissions and Hooks

How this repo reduces permission prompts without giving up safety. All of it lives in `config/` and is merged into the global `~/.claude/settings.json` by the installer.

## The model

A tool call is decided by, in order:

1. **PreToolUse hooks** (below): fast read-only check, the inline-interp/WebFetch blocks, the make/mise/go-tool guards, and finally the impact judge. A hook can `allow`, `ask`, or `deny`.
2. **Explicit rules** (`allow` / `ask` / `deny` in `permissions.json`): concrete commands. Precedence is `deny` > `ask` > `allow`.
3. **`defaultMode`**: what happens to anything no hook decided and no rule matched.

The `ask` list is the important one: it pins the always-prompt commands so they prompt regardless of mode. The `allow` list still exists for fast, obvious cases, but it is no longer exhaustive: the impact judge (the catch-all hook) is what handles the long tail, so the lists below do not need to enumerate every safe command.

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

Allow rules match each subcommand of a compound command independently, so a read-only exploration like `cd x && grep ... | grep -v ...` can still prompt when one piece does not cleanly match. A `PreToolUse` hook (`keru-safe-read`, a fast deterministic script, not an agent) handles that: it parses the command with shell-aware tokenizing (handling pipelines, loops, conditionals, safe redirections like `2>/dev/null`, and command substitution whose contents are themselves read-only) and auto-approves it only if every segment is a known read-only command (`grep`, `find`, `sed`, `awk`, `cat`, `ls`, `git log/diff/status`, `go fmt/build/test/list`, `mise ls/registry`, `gh` read subcommands including `gh api graphql` introspection/queries that carry no `mutation`, `base64`, ...) with no state-changing flags (`sed -i`/`perl -i` in-place edit, `find -exec/-delete`; note `-i` is only treated as dangerous for sed/perl, not for `grep -i`), no file redirection (a redirect operator like `>`, not a `->` inside a quoted string), and no arbitrary interpreter. Anything it cannot prove safe it leaves alone, deferring to the next hook. It never blocks.

## The inline-interpreter block

A `PreToolUse` hook (`keru-block-inline-interp`) denies running code inline via `python3 -c`, `node -e`, `ruby -e`, `perl -e`, and tells Claude to use the dedicated tool instead (`yq` for YAML, `jq` for JSON, `actionlint` for workflows). Inline interpreters are arbitrary code and the wrong tool for parsing/validation. Running a script file (`python3 foo.py`) is not blocked, only the inline-code flags.

## The impact-judge hook (catch-all)

Anything `keru-safe-read` does not approve falls to a final `PreToolUse` agent hook that judges one question: does the command leave the machine or is it irreversible? It reads the command and any files it references, then:

- **allow** if local and reversible: reads/analyzes, or writes/deletes files in the repo working tree or `/tmp` (git can revert the repo), including formatters, codegen, OpenAPI splitters, build, test, and moving/copying local files, even when they write into the repo;
- **ask** if it changes remote state or infra (push, deploy, terraform/kubectl/cloud mutations, DB changes), destroys what git cannot recover (`rm -rf` outside the repo, `reset --hard`, `checkout --`, `restore`, `clean`), or runs unclassifiable code (an arbitrary network package, an opaque script);
- **ask** whenever it cannot confidently tell it is local; it never denies.

This replaces ever-growing allow lists: instead of enumerating safe commands, the hook judges impact. Cost: a few seconds on commands the fast read-only check did not already approve.

## The WebFetch guard

A `PreToolUse` hook on `WebFetch` (`keru-block-webfetch`) denies any fetch to a Jira (`*.atlassian.net`) or GitHub URL and tells Claude to use the `jira` / `gh` CLI instead. Those systems are authenticated (WebFetch cannot read them) and have a proper CLI. This is a mechanical backstop for the playbook's "Jira and GitHub: always the CLI, never WebFetch" rule: the deny does not depend on Claude remembering it. Other URLs are unaffected.

## Changing it

Edit `config/permissions.json` or `config/hooks.json`, then re-run `scripts/install.sh`. The installer syncs: it tracks the rules and hooks it manages (under a `_keruManaged` marker in the settings), so each run adds what is new and removes what you dropped from config, while leaving rules you added elsewhere untouched (including the playbook's `SessionStart` hook). Changes apply to new sessions.
