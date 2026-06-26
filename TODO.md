# TODO / Ideas

A running list of ideas for this repo. Numbers are stable IDs; add new ideas at the end.

## Ideas

### 1. Dependabot PR review agent + security alerts triage — DONE

Built as the `keru-bot-triage` skill (its own `/keru-bot-triage` command) + the `keru-bot-triage` helper. Scope grew from Dependabot-only to all dependency/security bots: classified by section (dependabot / frogbot / sdk-gen / release / mise / renovate / other-bot) with a security flag, because one bot author (github-actions) opens many PR types and Frogbot has no author of its own (recognized by the title). CodeRabbit (a reviewer bot) is out of scope. Repo list lives only in memory, no default. Read-only, never merges.

### 2. `keru-responding-to-ci` skill — DONE

Built as `skills/keru-responding-to-ci/SKILL.md`, documented in docs/skills.md and README. Orchestrator: triages each red check (flaky/infra -> mark and stop; cause obvious -> writing-code; cause in doubt -> debugging then writing-code), verifies the fix locally. Read-only on CI; never reruns (`gh run rerun` is `ask`) or pushes (`git push` is `ask`). Does not write fixes or validate causes itself; it routes to the skills that own those.

A lightweight skill for "a PR has red CI, fix it": read the failing run via `gh`, locate the failing step, fix it. The skill is its own `/keru-responding-to-ci` command (no wrapper layer). Fills the gap between `keru-writing-code` and nothing.

**Trigger:** "CI is red", "fix the failing checks on this PR", or the command. Follows the Playbook: get the PR first (it's the input).

**Procedure:**

1. Identify the PR and its red checks: `gh pr checks <pr>`.
2. Per failing check, pull the failing logs: `gh run view <id> --log-failed`.
3. Classify the failure: lint/format, type error, build, real test, or flaky/infra.
4. Validate each problem before touching it, then fix locally and verify locally (re-run the lint/test that failed) before claiming anything.
5. Output: what failed, why, and the fix. The user does the push.

**Decisions:**

- Independent skill, not a router. `keru-responding-to-ci` does the full job on its own: triage the CI failures AND fix them. It gets the checks and triages each one; when a failure needs root-cause analysis it USES the `keru-debugging` skill (idea 3) as a sub-step, the same way `keru-writing-code` can use it, then writes the fix itself. Debugging is an optional tool it reaches for, not a forced hop. (Supersedes the earlier "router chain, does not write fixes" model.)
- Flaky / infra failures: mark and stop. If a failure looks flaky or infra-related (timeout, runner died, network), report it as such and do NOT touch code. Rerun stays a user decision (`gh run rerun` is in `ask` anyway).

**Security (already aligned with repo config, no new design):**

- Reading CI (`gh pr checks`, `gh run view/list`) is in `allow` -> diagnosis runs without prompts.
- `gh run rerun` is in `ask` -> re-triggering CI is never automatic.
- `git push` is in `ask` -> the fix is delivered locally; the push stays with the user.

### 3. `keru-debugging` skill (root-cause analysis in code) — DONE

Built as `skills/keru-debugging/SKILL.md`, documented in docs/skills.md and README. Independent skill AND a called capability (responding-to-ci and writing-code can invoke it). Validates the root cause with evidence (reproduce -> isolate -> hypothesis+verify -> root cause not symptom) and stops; does NOT write the fix. Distinct from keru-investigation (a doc deliverable).

A skill for "this is broken, find out why", distinct from `keru-investigation` (which produces a doc). Proposed method:

1. Reproduce the failure first (failing test, command, input). If it can't be reproduced, that's the first finding, don't proceed blind.
2. Isolate: narrow down where it happens (bisect, logs, binary search over the diff/commits) before theorizing.
3. Hypothesis -> verify: one candidate cause at a time, confirmed with evidence, not "this should be" (ties into the verify-don't-assume rule).
4. Root cause, not symptom: distinguish the real fix from a patch; if it's only a patch, say so explicitly.
5. Output: root cause + full error context. Debugging does NOT write the fix itself; it gathers the complete error context and hands off to `keru-writing-code`, which applies it.

**Decisions:**

- Independent skill AND a shared capability. `keru-debugging` works on its own ("this is broken, find out why"), and is also the root-cause tool that other skills invoke when they need it (`keru-writing-code`, `keru-responding-to-ci`). Like a reusable helper, not a fixed link in a chain.
- Diagnose only, do NOT fix. It returns root cause + full error context; whoever called it writes the fix (writing-code applies it; responding-to-ci applies it). This keeps it composable: a caller that already knows how to write fixes just needs the diagnosis.
- Per principle #1: debugging owns the root-cause method in one place; callers reuse it rather than restating it.

### 4. Repo self-health tooling — DONE

Built as the local `repo-health` skill. See `repo-health/README.md` and `docs/architecture.md`. (ID kept; entry removed.)

### 5. Memory discipline conventions — DONE

Built as [docs/memory.md](docs/memory.md), linked from README and getting-started. States the boundary (shared rule vs personal choice) and references the harness memory rules without restating them. Worked example: the bot-triage repo list lives in memory, the skill in the repo.

### 6. Turn this repo into a Claude Code plugin

Explore packaging the repo as a Claude Code plugin instead of the install-script-plus-symlinks setup. Open questions: does the plugin format cover skills, commands, permissions, and hooks the way the installer does today; what replaces `scripts/install.sh`; how the playbook `SessionStart` hook and the `keru-*` PATH helpers fit; whether it stays a single source of truth. Investigate the plugin spec first, then decide if it is worth migrating.
