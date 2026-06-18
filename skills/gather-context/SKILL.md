---
name: gather-context
description: Gather read-only context for a task from any starting point: a Jira ticket/epic, a GitHub PR, a repo, or a file reference. Resolves the chain in both directions (PR to ticket and ticket to PRs) and can read repos that are not cloned locally. Use when given a ticket key, a Jira/GitHub URL, or asked to understand a task before acting. Satisfies the Playbook's mandatory "ask for the ticket" and "follow the chain" steps.
---

# Gather Context

Resolve everything needed to act on a task, read-only, from whatever the user hands you. Apply the Playbook's "First Step": get the ticket, then follow its chain of context before doing anything. This skill is the *how*; the rule is in the Playbook.

## Prerequisite

`jira-cli` and `gh` must be installed and authenticated (see [docs/tools.md](../../docs/tools.md)). If a CLI is missing or not configured, tell the user to run setup instead of guessing contents.

## Resolve the starting point

The input can be any of these; identify which and start there:

- **Jira key** (`DBI-1234`): a ticket. No prefix? Use the default project or ask.
- **Jira URL** (`.../browse/DBI-1234`): extract the key from `/browse/`.
- **Jira epic**: list its children for full scope.
- **GitHub PR URL/number**: read the PR.
- **A repo or file reference** (e.g. `owner/repo`, or a path in another service): read it remotely (see "Reading repos not cloned locally").

## Follow the chain (MANDATORY, not optional)

Reading the single ticket is never enough. You MUST resolve and read its chain before doing any work. Do every step that applies; do not skip a step because the ticket "seems clear". Walk one hop out from the starting ticket (the investigation's own links do not need to be expanded further once you have read it).

1. **Read the ticket's raw fields** (`jira issue view <KEY> --raw`) to see parent, epic, and every linked issue. The `--plain` view hides links; the raw JSON does not.
2. **Fetch every linked issue and the parent/epic** (`jira issue view <LINKED-KEY> --plain --comments 10`). Read them, do not just list them.
3. **If a linked or "created by" issue is an investigation, reading it is REQUIRED.** An investigation holds the rationale behind the acceptance criteria (why a value is what it is, why a field must not be set). Read the investigation ticket in full.
4. **Find and open the investigation's artifacts.** An investigation's conclusions usually live in a merged PR and a markdown document, not only in the Jira description. Find the PRs two ways, preferring the first:
   - **Jira Development panel (preferred, most accurate).** Jira links PRs, branches, and deployments to an issue under its "Development" panel. That data is NOT in `jira issue view --raw`; it comes from the dev-status endpoint. Run `keru-jira-dev <KEY>` (a read-only helper installed on PATH by the installer, allowlisted so it does not prompt). It returns JSON with `pullRequests[]` (each with `url`, `status`, `branch`), `branches[]`, and `repositories[]`. An empty `pullRequests` means nothing is linked in the panel; use the fallback below.
   - **Fallback: search GitHub by key.** If the panel is empty or unavailable, `gh pr list --repo <owner>/<repo> --search "<INVESTIGATION-KEY> OR <TICKET-KEY>" --state all --json number,title,headRefName,state,url`.
   - Open the relevant PR(s): `gh pr view <n> --repo <owner>/<repo> --json title,state,url,files,body` and read the changed files (the investigation doc) via `gh pr diff <n> --repo <owner>/<repo>` or by reading the file (locally if cloned, else `gh api repos/<owner>/<repo>/contents/<path>`).
   - If the investigation references a doc path, branch, or another repo, follow it and read it. Do not stop at the Jira ticket.
5. **From a PR starting point:** read it (`gh pr view <n> --repo <owner>/<repo> --json number,title,headRefName,baseRefName,url,body,files`), take the branch from `headRefName`, scan branch and body for a Jira key (`DBI-\d+`), fetch that ticket, then run steps 1-4.

### Gate before acting

Do not begin the task until you can answer all of these. If any is "no", keep gathering:

- Have I read the raw fields and every linked issue, parent, and epic?
- If an investigation exists, have I read the investigation ticket AND its PR/document, not just its title?
- Do I understand the rationale behind each acceptance criterion (including any "do NOT do X")?

Then tell the user what you read (linked tickets, the investigation and where its conclusions live, PRs, files) before proceeding.

## Fetching commands (read-only only)

- Ticket: `jira issue view <KEY> --plain` (`--comments 10` for discussion). `jira issue view` only supports `--plain`, `--comments`, and `--raw`; it has no `--no-truncate` (that flag is on `jira issue list`).
- Raw fields (parent, links, all fields): `jira issue view <KEY> --raw`. Read the JSON directly; never pipe it into `python3 -c`, `node -e`, or any interpreter. Inline-code execution is arbitrary code and is correctly blocked; use the CLI's own flags.
- Epic children: `jira epic list <EPIC-KEY> --plain`. Children of a parent: `jira issue list -P <PARENT-KEY> --plain --no-truncate`.
- PR: `gh pr view <n> --repo <owner>/<repo> --json ...`. PRs by key: `gh pr list --repo <owner>/<repo> --search "<KEY>" --state all --json ...`.

## Reading repos not cloned locally

Per the Playbook's "Never fabricate" rule, when context lives in another repo, do not guess: read it remotely with `gh`, no clone needed.

- A file's contents: `gh api repos/<owner>/<repo>/contents/<path> --jq '.content' | base64 -d` (or `gh api .../contents/<path>?ref=<branch>`).
- List a directory: `gh api repos/<owner>/<repo>/contents/<dir>`.
- Search code across a repo or org: `gh search code "<query>" --repo <owner>/<repo>` (or `--owner <org>`).
- A PR's changed files and diff: `gh pr diff <n> --repo <owner>/<repo>`.

Prefer the local copy if the repo is already checked out; only go remote when it is not.

## Using the context

Treat the ticket plus its chain as the source of truth per the Playbook: work type, acceptance criteria, scope, and the rationale behind them. Do not invent acceptance criteria. If anything is thin or ambiguous, surface it to the user rather than guessing. Briefly tell the user what you read (linked tickets, investigation, PRs, remote files) so the chain is visible.

## Read-only boundary

Per the Playbook's "Read-only by default for external tools" rule, this skill only reads. It may read issue, epic, PR, and repo content, and may inspect CI (`gh run view/list`, `gh pr checks`, workflow logs). No state changes: no `jira issue create`/transitions/comments/edits; no `gh pr create`/merge/review/comment/close; no triggering, re-running, or toggling workflows. A state-changing action must be requested explicitly, as a separate step outside this skill.
