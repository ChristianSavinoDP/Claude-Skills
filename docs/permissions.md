# Permissions and Hooks

How this repo reduces permission prompts without giving up safety. All of it lives in `config/` and is merged into the global `~/.claude/settings.json` by the installer.

## The model

A tool call is decided by, in order:

1. **PreToolUse hooks** (below): the deliverable-write gate, the inline-interp/WebFetch blocks, and the Bash command gate (`keru-safe-read`, fast static path plus a model fallback for the unknowns). A hook can `allow`, `ask`, or `deny`.
2. **Explicit rules** (`allow` / `ask` / `deny` in `permissions.json`): concrete commands. Precedence is `deny` > `ask` > `allow`.
3. **`defaultMode`**: what happens to anything no hook decided and no rule matched.

The `ask` list is the important one: it pins the always-prompt commands so they prompt regardless of mode. The `allow` list still exists for fast, obvious cases, but it is no longer exhaustive: the Bash command gate handles the long tail (fast for read-only, a model verdict for the rest), so the lists below do not need to enumerate every safe command. A command you approve with "allow always" is added to `allow` and short-circuits future prompts.

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
- DataDog reads (`pup`): `error-tracking issues search/get`, `logs search/aggregate/list/query`, `events search/list`, `metrics query/search/list`, `auth status`. Every `pup` write (`cases create/jira`, `metrics submit`, `logs archives/metrics delete`, `metrics metadata update`) is in ask, below
- Read-only tool helpers: `keru-jira-dev`, `keru-bot-triage`, and `keru-branch-cleanup audit` (the audit mode only inspects; its `clean` mode is in ask, below)
- `keru-repo-update` (both `audit` and `update`): audit is read-only; update is local-reversible (stashes are restorable, and a `--ff-only` pull only moves a pointer, never rewrites history or resolves a conflict, and skips diverged repos), so it fits the local-reversible line and never prompts. The skill itself gates it by showing the plan for confirmation first (`disable-model-invocation: true`)

`make`, `mise`, and `go tool` are deliberately NOT in allow; they go through a hook (below).

## ask: always prompts

Destructive actions (per the playbook's definition), so they prompt even under `acceptEdits`:

- `git commit`, `git push`
- Discarding uncommitted work: `git reset --hard`, `git checkout -- <files>`, `git restore`, `git clean`
- `keru-branch-cleanup clean`: deletes local branches whose upstream is gone (not git-recoverable), so it prompts once before the batch; its `audit` mode is read-only and in allow
- `terraform apply`, `terraform destroy`
- Jira writes: `issue create/move/assign/comment/edit`, `epic add/create`, `sprint`
- GitHub writes / CI triggers: `pr create/merge/review/comment/close/edit`, `run rerun/cancel`, `workflow run/enable/disable`
- DataDog writes (`pup`): `cases create/jira`, `metrics submit`, `metrics metadata update`, `logs archives/metrics delete` (remote mutations, out of scope for the read-only audit)

## The Bash command gate (`keru-safe-read`): one hook, fast path + model fallback

Every Bash command goes through a single `PreToolUse` hook with two paths:

**Fast path (instant, deterministic).** The script parses the command with shell-aware tokenizing (pipelines, loops, conditionals, safe redirections like `2>/dev/null`, and command substitution whose contents are themselves read-only) and auto-approves it the moment every segment is provably read-only or local-reversible: `grep`, `find`, `sed`, `awk`, `cat`, `ls`, `git log/diff/status/fetch` (including the `git -C <clone> fetch` form), `go fmt/build/test/list/get/tool` (bare), `pip list/show`, `python -m py_compile`, `mise ls/registry`, `gh`/`jira` read subcommands (`gh api` only as a GET), `pup` read subcommands (`error-tracking/logs/events/metrics` search/aggregate/query, `auth status`), `base64`, ... with no state-changing flags (`sed -i`/`perl -i`, `find -exec/-delete`; `-i` is dangerous only for sed/perl, not `grep -i`), no file redirection, and no arbitrary interpreter. The read-only majority of commands hit this path and never touch a model.

**Slow path (only for the rest).** A command the fast path cannot prove safe (a `make`/`mise` target whose recipe is hidden, a `docker`/`kubectl`/`aws` call, anything unrecognized) used to fall to a separate agent hook that ran on *every* command and added latency to everything. Now the same hook makes a single model call (`dp ai claude`, see [external-tools.md](external-tools.md)) to judge one question: does any part mutate remote state/infra or destroy something irreversibly?

- **allow** if local and reversible: reads (locally or a read-only remote query), build/test/lint/format/codegen, writes/deletes files in the repo or `/tmp` (git reverts), dependency fetches (`go get`, `npm/pip install`), a recognized linter/formatter via `npx`/`go run @v`/`uvx`, `brew install`;
- **ask** if it changes remote state/infra (push, deploy, terraform/kubectl/cloud mutations, DB changes), destroys beyond git's reach (`rm -rf` outside the repo, `reset --hard`, `checkout --`, `restore`, `clean`), or executes an unrecognized remote payload (`curl ... | sh`, `go install` of an unfamiliar package);
- **fail-safe ask** on any failure (no `dp`, timeout, unclear): an unevaluated unknown command always prompts, never auto-allows. It never denies.

This is why it is one hook, not a fast one plus an always-slow agent: the model is consulted only for the genuinely unknown commands, so the read-only majority stays instant. A command you approve with "allow always" lands in `permissions.allow` (below) and Claude Code's permission layer handles it, so it does not re-incur the model call.

## The deliverable-write gate (`keru-gate-deliverable`)

Streamed chat text cannot be validated before you see it, so a skill deliverable is written to a file first and shared from there. A `PreToolUse` hook on `Write`/`Edit` enforces that mechanically: when the path is `/tmp/keru-deliverable-<skill>.md` (or `/tmp/keru-deliverable-<skill>-<id>.md`, where the optional `<id>` is a Jira key or PR number that keeps concurrent or sequential deliverables of the same skill from overwriting each other), it validates the content against that skill's Output contract (the same checkers as `keru-check-output`: the required opening, no em dashes) before the file is written. If it does not comply, the hook returns `deny`, so the file is never created and Claude is told why and retries. The `<skill>` segment in the filename selects which contract applies (matched as the longest known skill name, so a hyphenated skill is not split on the `<id>` hyphen). Any other Write/Edit is untouched. This is the one place enforcement is mechanical rather than reactive: unlike a Stop hook (which runs after the message is shown), a denied write means the bad deliverable never reaches disk.

## The inline-interpreter block

A `PreToolUse` hook (`keru-block-inline-interp`) denies running code inline via `python3 -c`, `node -e`, `ruby -e`, `perl -e`, and tells Claude to use the dedicated tool instead (`yq` for YAML, `jq` for JSON, `actionlint` for workflows). Inline interpreters are arbitrary code and the wrong tool for parsing/validation. Running a script file (`python3 foo.py`) is not blocked, only the inline-code flags.

## The WebFetch guard

A `PreToolUse` hook on `WebFetch` (`keru-block-webfetch`) denies any fetch to a Jira (`*.atlassian.net`) or GitHub URL and tells Claude to use the `jira` / `gh` CLI instead. Those systems are authenticated (WebFetch cannot read them) and have a proper CLI. This is a mechanical backstop for the playbook's "Jira and GitHub: always the CLI, never WebFetch" rule: the deny does not depend on Claude remembering it. Other URLs are unaffected.

## The Stop hooks (skill and output gates)

Three `Stop` hooks (they run when Claude finishes a turn) are mechanical backstops for rules that text alone failed to enforce. All are bounded (at most one block per turn, via `stop_hook_active`) and fail open, so they never wedge a session.

- **`keru-require-skill`:** if you explicitly said "use the X skill" and the turn ended without that skill's `Skill` tool actually firing, it blocks once and tells Claude to invoke it. It only fires on an explicit "use" instruction, not casual mentions or automatic triggering (see [skills.md](skills.md)).
- **`keru-check-output`:** enforces a deliverable skill's Output contract, the machine-checkable part. Each deliverable skill defines a concrete opening (pr-review opens with the verdict line, writing-tickets/pr-description/bot-triage/datadog-audit/addressing-pr-comments with a bold header, investigation with a markdown heading); the hook also forbids em dashes in deliverable prose (including the fenced block pasted into a PR). It checks only the opening and em dashes, only when the message clearly IS the deliverable (a clarifying question or trailing content after a correct opening is left alone), and it detects the deliverable even when the skill was never explicitly loaded, via its structural form.
- **`keru-judge-output`:** the second layer, for the rules a regex cannot check (tone, claims asserted without verification, a remembered-but-wrong shape). When a turn produces a deliverable for `pr-review`, `writing-tickets`, `pr-description`, `addressing-pr-comments`, `bot-triage`, or `datadog-audit`, it sends the delivered text plus the skill's rules to a headless Claude judge (`dp ai claude`) that reads it as a fresh reviewer and blocks once if it clearly violates the skill. It runs only after the regex gate says the form is right (so it never judges chat or doubles up), and it is excluded for `investigation` because that skill already runs its own adversarial-review subagent. Cost: one short model call per actual deliverable, none on ordinary turns. This is the mechanical version of "have a second pair of eyes check it," for the judgment-level rules Claude kept failing to self-apply.

## The drift check (`keru-check-drift`)

A `SessionStart` hook (they run at session start; their stdout becomes context for Claude) that warns when the active install is stale. It exists because this repo activates by mechanisms with different staleness rules, and none is covered by any built-in Claude Code check (a plain skills directory is not version tracked): symlinked skills and the cat'd playbook are live (editing them needs no reinstall), but a newly added or removed skill, a `config/*.json` edit, and any helper/hook script edit only take effect on `scripts/install.sh`, because those are copied/merged, not symlinked. It prints a short notice, only when there is drift, for two independent signals:

- **Behind origin:** HEAD is behind the remote default branch. Local refs only, no `git fetch`, so it is "as of your last fetch" and adds zero startup latency; only checked when you are actually on the default branch, so feature-branch work is not nagged.
- **Repo changed since install:** the set of activatable artifacts (skill dir names, `config/*.json`, the `scripts/` helpers and hooks, `install.sh`) differs from what was present at the last install. The installer records that state with `keru-check-drift --write-marker` into `~/.claude/.keru-installed-rev`; the hash logic lives only in the helper, so the marker and the check can never drift apart. The hash deliberately excludes file contents inside a skill (those are live via the symlink), so editing a `SKILL.md` never triggers it, only adding/removing a skill does.

Fail-open in every branch: any error prints nothing and exits 0, so a broken check never delays or disrupts a session. The installer injects it (with the machine's repo path resolved at runtime, like the playbook `cat`) and `uninstall.sh` removes both the hook and the marker.

## Changing it

Edit `config/permissions.json` or `config/hooks.json`, then re-run `scripts/install.sh`. The installer syncs: it tracks the rules and hooks it manages (under a `_keruManaged` marker in the settings), so each run adds what is new and removes what you dropped from config, while leaving rules you added elsewhere untouched (including the playbook's `SessionStart` hook). Changes apply to new sessions.
