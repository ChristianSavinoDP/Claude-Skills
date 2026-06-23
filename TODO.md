# TODO / Ideas

A running list of ideas for this repo. Numbers are stable IDs; add new ideas at the end.

## Ideas

### 1. Dependabot PR review agent + security alerts triage

Build an agent (skill) that reviews Dependabot PRs and surfaces security issues from the repo's GitHub Security tab.

- Review open Dependabot dependency-bump PRs (what changed, changelog/release notes, breaking changes, whether it's safe to merge).
- Read the repo's Security tab via `gh`: Dependabot security alerts / advisories, severity, affected paths, and whether an open PR already fixes them.
- Correlate: map each security alert to the PR that resolves it, and flag alerts with no PR yet.
- Repo set: the agent runs over multiple repos, not one. A default list is kept in memory.
- Repo resolution: if no repos are known in memory, ask the user for them. Validate each input against GitHub (e.g. `gh repo view`) before acting, and re-ask on bad input (user typo / nonexistent repo) instead of guessing.
- The user can override the repo list when invoking the command that activates the agent (add/remove/replace repos for that run), and can ask to persist changes to the default list in memory.
- Example repo that has these: `xapi`.

**Shape:** a skill (`dependabot-triage` or similar) + a `/keru-dependabot-triage` command that loads it. Command is a shortcut, not a requirement, like the rest.

**Repo list (decided):** a fixed list kept in a memory file. No autodiscovery. If the list is missing, ask; validate each repo with `gh repo view <owner/repo>` before acting and re-ask on bad input. The user can override the list per run (add/remove/replace) and can ask to persist changes back to memory.

**Per-repo procedure (read-only):**

1. List open Dependabot version-update PRs: `gh pr list --state open --json number,title,author --jq '... | select(.author.login | test("dependabot"))'`. Author shows as `app/dependabot`.
2. Per PR: bump (old -> new), checks (`gh pr checks`), changelog/release notes.
3. Security alerts via `gh api repos/<R>/dependabot/alerts?state=open&per_page=100` (paginate). Source of truth is the API, not the UI count (see findings).
4. Correlate alert <-> resolving PR; flag alerts with no PR.
5. Classify each item: routine dependency update vs security issue.

**Investigation findings (verified on `dailypay/xapi`, 2026-06-23):**

- Dependabot has two independent mechanisms: version-update PRs and security alerts. In xapi they're fully decoupled: 4 open update PRs (stubbed-services, minor group, actions/checkout, terraform servicemesh) and 16 open security alerts (3 high / 9 medium / 4 low), all in `api-docs/package-lock.json` (undici, ws, protobufjs, dompurify, js-yaml, @opentelemetry/core). None of the 4 PRs touch that manifest, so every security alert currently has NO resolving PR. This is the exact "alert with no PR" case the agent must surface, and confirms correlation is mandatory.
- A `[security]` fix can come from a non-Dependabot author: PR #3176 (`upgrade golang.org/x/net [security]`) was opened by `app/github-actions`. So detect security fixes by content/label, not just by author = dependabot, or they're missed.
- API vs UI count diverges: API returns 16 open alerts (all unique GHSA); the Security tab showed 14. The UI groups/counts differently. Treat the API as source of truth and note the UI number may differ instead of trusting the visual count.

**Decisions:**

- Output: classify each item as either a routine dependency update or a security issue, so the user can tell them apart at a glance and prioritize the security ones.
- Scope: read-only by default. Never auto-merge: merging is always a human action, no exceptions. The most the user can opt into per run is auto-approving a PR whose checks are green; the merge itself stays with the user. Gate even that on the repo's own permission config: `gh pr review` / `gh pr merge` currently sit in the `ask` list (`config/permissions.json`) and the Bash safety-judge hook treats them as remote mutations, so auto-approve is NOT allowed today. Until that permission is explicitly granted, the agent stays read-only.

### 2. `responding-to-ci` skill (fast, with a command)

A lightweight skill for "a PR has red CI, fix it": read the failing run via `gh`, locate the failing step, fix it. Ships with a `/keru-responding-to-ci` command (shortcut, not a requirement). Fills the gap between `writing-code` and nothing.

**Trigger:** "CI is red", "fix the failing checks on this PR", or the command. Follows the Playbook: get the PR first (it's the input).

**Procedure:**

1. Identify the PR and its red checks: `gh pr checks <pr>`.
2. Per failing check, pull the failing logs: `gh run view <id> --log-failed`.
3. Classify the failure: lint/format, type error, build, real test, or flaky/infra.
4. Validate each problem before touching it, then fix locally and verify locally (re-run the lint/test that failed) before claiming anything.
5. Output: what failed, why, and the fix. The user does the push.

**Decisions:**

- Boundary / job: the skill's sole job is CI failures, nothing broader ("solo se dedica a eso"). It gets the checks and TRIAGES each one: does the cause need debugging or not? If it does, it calls the debugging skill (idea 3), which gathers context and hands to writing-code for the fix. responding-to-ci itself does not write fixes; it routes. Flaky/infra -> mark and stop (no handoff).
- Flaky / infra failures: mark and stop. If a failure looks flaky or infra-related (timeout, runner died, network), report it as such and do NOT touch code. Rerun stays a user decision (`gh run rerun` is in `ask` anyway).

**Security (already aligned with repo config, no new design):**

- Reading CI (`gh pr checks`, `gh run view/list`) is in `allow` -> diagnosis runs without prompts.
- `gh run rerun` is in `ask` -> re-triggering CI is never automatic.
- `git push` is in `ask` -> the fix is delivered locally; the push stays with the user.

### 3. `debugging` skill (root-cause analysis in code)

A skill for "this is broken, find out why", distinct from `investigation` (which produces a doc). Proposed method:

1. Reproduce the failure first (failing test, command, input). If it can't be reproduced, that's the first finding, don't proceed blind.
2. Isolate: narrow down where it happens (bisect, logs, binary search over the diff/commits) before theorizing.
3. Hypothesis -> verify: one candidate cause at a time, confirmed with evidence, not "this should be" (ties into the verify-don't-assume rule).
4. Root cause, not symptom: distinguish the real fix from a patch; if it's only a patch, say so explicitly.
5. Output: root cause + full error context. Debugging does NOT write the fix itself; it gathers the complete error context and hands off to `writing-code`, which applies it.

**Decisions:**

- Diagnose + gather context, do NOT fix. Debugging finds the root cause and assembles the full error context, then calls `writing-code` to apply the fix. (This supersedes an earlier "diagnoses and may fix" note: debugging does not write the fix.)
- Escalation chain (routers, each hands to the next): `responding-to-ci` -> `debugging` -> `writing-code`.
  - `responding-to-ci`: gets the checks, triages whether the cause needs debugging; if so, calls debugging. Flaky/infra -> mark and stop (no handoff).
  - `debugging`: gathers the full error context + root cause, then calls writing-code.
  - `writing-code`: writes the fix.
- Clean separation per principle #1: each skill owns exactly one thing (CI triage / root-cause + context / writing the fix). No skill restates another's method.

### 4. Repo self-health tooling — DONE

Built as the local `repo-health` skill. See `repo-health/README.md` and `docs/architecture.md`. (ID kept; entry removed.)

### 5. Memory discipline conventions

Document the (currently implicit) conventions for what belongs in memory vs. in the repo. The harness already has detailed memory rules (user/feedback/project/reference types, frontmatter, the `MEMORY.md` index, don't duplicate what the repo records), but they live in the harness config, not in this repo, and nothing here states the user's own memory-vs-repo boundary.

**The line (refined):** the test is "shared rule" vs "personal choice", NOT "reproducible vs not".

- Repo = rules that apply to anyone using the repo (skills, permissions, hooks). Shared.
- Memory = the user's personal choices and context (who they are, their corrections, and choices like which repos to triage). Personal.

A whitelisted command is a repo rule (applies to everyone); a list of repos to triage is a personal choice. Different scopes, so no principle #1 violation, not the same thing duplicated in two places.

**No conflict with idea 1:** the Dependabot repo list correctly lives in memory. The user chooses those repos; it's a personal choice, not project config like whitelisting a command. Idea 1 stays as decided (fixed list in a memory file).

**Form:** likely a short `docs/memory.md` that states the boundary and references the harness memory rules rather than restating them (consistent with docs/ explaining design without repeating rules). Not a playbook section (kept short on purpose) and not a skill (saving memory isn't a task like reviewing a PR). Location to confirm when building.
