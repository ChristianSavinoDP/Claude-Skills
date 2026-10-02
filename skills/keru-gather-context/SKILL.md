---
name: keru-gather-context
description: Gather read-only context for a task from any starting point: a Jira ticket/epic, a GitHub PR, a repo, or a file reference. Resolves the chain in both directions (PR to ticket and ticket to PRs) and can read repos that are not cloned locally. Use when given a ticket key, a Jira/GitHub URL, or asked to understand a task before acting. Satisfies the Playbook's mandatory "ask for the ticket" and "follow the chain" steps.
---

# Gather Context

Resolve everything needed to act on a task, read-only, from whatever the user hands you. Apply the Playbook's "First Step": get the ticket, then follow its chain of context before doing anything. This skill is the *how*; the rule is in the Playbook. The Playbook's "Shared Standards" apply throughout (read-only by default, never fabricate, verify do not assert).

## Prerequisite

`jira-cli` and `gh` must be installed and authenticated (see [docs/external-tools.md](../../docs/external-tools.md)). If a CLI is missing or not configured, tell the user to run setup instead of guessing contents.

## Resolve the starting point

Jira and GitHub are reached only through the installed `jira` and `gh` CLIs (authenticated, present on this machine). Do not look for an MCP server and do not use WebFetch: WebFetch cannot read authenticated Jira/GitHub content and bypasses the right tool. A URL is just a carrier for an id: extract it and use the CLIs below. If a CLI is genuinely missing or unconfigured, say so and stop; never fall back to WebFetch or guess.

The input can be any of these; identify which and start there:

- **Jira key** (`DBI-1234`): a ticket. No prefix? Use the default project or ask.
- **Jira URL** (`.../browse/DBI-1234`): extract the key from `/browse/`, then treat it as a Jira key.
- **Jira epic**: list its children for full scope.
- **GitHub PR URL/number** (`github.com/<owner>/<repo>/pull/<n>`): extract owner/repo/number from the URL.
- **A repo or file reference** (e.g. `owner/repo`, or a path in another service): read it remotely (see "Reading repos not cloned locally").

## Follow the chain (MANDATORY, not optional)

Reading the single ticket is never enough. You MUST resolve and read its chain before doing any work. Do every step that applies; do not skip a step because the ticket "seems clear". Walk one hop out from the starting ticket, plus the keys the chain's text mentions (step 2); the investigation's own links do not need to be expanded further once you have read it.

Read the chain yourself; do not hand it to subagents. The snapshot already holds every chain item's description and comments, so delegating saves no fetch, and what you are gathering is the *why* behind the acceptance criteria, which does not survive someone else's summary. Reads the snapshot does not hold (an investigation's PR and doc, the sources the map in step 5 names) are independent, so issue them concurrently, and read every result.

1. **Get the ticket and snapshot the chain in the same pass.** Run `keru-context-snapshot check <KEY>`; if it is not `current`, run `keru-context-snapshot write <KEY>`. That walks the chain with no model at all (root, parent, epic, every link, the keys the chain's text mentions, plus the dev panel's PRs) into `~/.claude/keru-context/<KEY>.md` as markdown. `write` returns a small JSON map: the `keys`, the `investigations` it found (linked or mentioned), `mentioned_keys`, the linked `pull_requests`, the path; `check` returns its `status`, the path and the same `investigations` list, and the PRs are in the file's last section. **Read the whole file**: the root ticket (description, acceptance criteria, comments) and every chain section. If a field looks missing, `jira issue view <KEY> --raw` is still the authority (the `--plain` view hides links; the raw JSON does not).
2. **A linked investigation is REQUIRED reading,** in full. An investigation holds the rationale behind the acceptance criteria (why a value is what it is, why a field must not be set). One the chain only mentions (listed in the file's Mentioned section) is opened (`jira issue view <KEY> --plain --comments 10`) to decide whether it bears on the work, never from its title; one that does is then read like a linked one, artifacts included (step 3). Keys the file lists as over the cap or unreadable carry no type: check them before concluding none is an investigation.
3. **Find and open the investigation's artifacts.** An investigation's conclusions usually live in a merged PR and a markdown document, not only in the Jira description. Find the PRs two ways, preferring the first:
   - **Jira Development panel (preferred, most accurate).** Jira links PRs, branches, and deployments to an issue under its "Development" panel. That data is NOT in `jira issue view --raw`; it comes from the dev-status endpoint. Run `keru-jira-dev <KEY>` (a read-only helper installed on PATH by the installer, allowlisted so it does not prompt). It returns JSON with `pullRequests[]` (each with `url`, `status`, `branch`), `branches[]`, and `repositories[]`. An empty `pullRequests` means nothing is linked in the panel; use the fallback below.
   - **Fallback: search GitHub by key.** If the panel is empty or unavailable, `gh pr list --repo <owner>/<repo> --search "<INVESTIGATION-KEY> OR <TICKET-KEY>" --state all --json number,title,headRefName,state,url`.
   - Open the relevant PR(s): `gh pr view <n> --repo <owner>/<repo> --json title,state,url,files,body` and read the changed files (the investigation doc) via `gh pr diff <n> --repo <owner>/<repo>` or by reading the file (locally if cloned, else `gh api repos/<owner>/<repo>/contents/<path>`). Once the panel/search hands you the PR set, these reads are independent: fetch the PRs and their docs concurrently, not one after another.
   - If the investigation references a doc path, branch, or another repo, follow it and read it. Do not stop at the Jira ticket.
   - **Read the recorded dispositions and corrections, not only the narrative doc.** An investigation's artifacts often include a delivery or task breakdown (e.g. a `task-breakdown.yaml`), review notes, or per-item disposition comments that record, for *this* ticket specifically, that an earlier framing was wrong or a value was corrected. That correction is the highest-value context for the work and the easiest to walk past, because the narrative doc reads complete on its own. Open the breakdown and the disposition notes, not just the story: a correction aimed directly at what you are about to build, already written down, is exactly what you must not re-derive wrong.
4. **From a PR starting point:** read it (`gh pr view <n> --repo <owner>/<repo> --json number,title,headRefName,baseRefName,url,body,files`), take the branch from `headRefName`, scan branch and body for a Jira key (`DBI-\d+`), fetch that ticket, then run steps 1-3 and 5.
5. **When the task changes code or infra (writing, fixing, or reviewing the change), map what it touches outside the code it changes, and open each at its source.** The chain says what to build; it rarely describes the systems around the change, and that is where reviewers find what the author missed. For each line, name the source you opened (`repo/path:line`), or `n/a` and why:
   - **Inputs:** who produces each input and what real values look like (the producer's code, not only the schema), and, when the code compares values over time, two consecutive ones.
   - **Outputs:** who reads each output (return value, event, row, metric, log) and what they do with it.
   - **Runtime:** what runs the code in its real environment (chart, sidecar or mesh, entrypoint, job lifecycle, env, timeouts), with each deploy-coupled value taken from the chart or terraform that sets it, and the permission each external call needs (ACL, IAM, grant) against what is actually granted.
   - **Upstream:** for each dependency the ticket names or the change adds or bumps, read what you call at the pinned version and on its default branch, to see what is changing in it.
   - **Precedent:** an existing implementation of the same kind of thing in the org (`gh search code`), whose shape you follow (its code, not its doc).

   Charts and terraform usually live in other repos (commonly `gitops`, `terraform-modules`): read the local clone, else `gh`. A line with no source opened is an assumption: open it, or ask before acting; never defer it as an "infra prerequisite" when it is readable.

### What is snapshotted, and what is never snapshotted

A ticket is a contract that freezes once the work starts, so re-walking its chain every session is waste. Code does not freeze, so it is never snapshotted. The line between them is the whole design:

- **In the snapshot:** the ticket and its chain (descriptions, comments, statuses, how each is linked), pointers to the keys its text mentions (type, status and summary as of the write, not re-verified by `check`), and pointers to the PRs from the dev panel. Reuse across sessions is legitimate *because* the file carries a validation header (per key: `updated`, `status`, comment count, link count) and `check` re-reads those four. `current` means verified current, not assumed current. A ticket's mutable part is its comment thread, its links and its workflow state, which is exactly what the fingerprint covers: so when the work turns on a linked dependency's status (is the blocker closed yet?), a `current` check is the answer, and re-fetching statuses by hand on the side is waste.
- **Never in the snapshot:** PR diffs, file contents, CI logs. Those move under you, and reviewing a stale diff means reviewing code that no longer exists. The snapshot carries the pointer (PR number, branch, url); the content is read live, every time.
- `stale` names which keys moved (or, with a `reason`, that the file is in an older format): rewrite it, do not reason from the old copy.

### Gate before acting

Do not begin the task until you can answer all of these. If any is "no", keep gathering:

- Was the snapshot written, or reported `current` by `check`, in *this* session, and have I read all of it myself, root and every chain section?
- Have I read every linked investigation AND its PR/document, not just its title, and opened every mentioned investigation, reading the ones that bear on the work the same way?
- Have I read the ticket's recorded dispositions and corrections (a delivery/task breakdown, review notes, per-item comments), not only the narrative doc, so a correction already written for this ticket is not re-derived wrong?
- Do I understand the rationale behind each acceptance criterion (including any "do NOT do X")?
- When step 5 applies, does every line of its map (inputs, outputs, runtime, upstream, precedent) name a source I opened, or `n/a` with the reason?
- For every concrete fact I took from the ticket or epic (a cadence, threshold, owner, channel, name), have I confirmed it against the repo artifact that defines it, rather than trusting the ticket's wording, which can be aspirational or stale?

Then tell the user, in a few lines, what you read (linked tickets, the investigation and where its conclusions live, PRs), whether the chain came from a snapshot `check` reported `current` or a fresh `write`, and, when step 5 applies, the map: one line per item with its source, or `n/a` and why. A line you could not open is a question for the user before acting, not a gap to report and move past; the map is how the user sees it before a reviewer does. When the calling skill writes a gated deliverable (a review, a comment resolution), this goes in the deliverable instead of chat: the read list and the map in its `Why:` line, and a line you could not open as one of its questions (to the author, in a review).

## Fetching commands (read-only only)

- Ticket: `jira issue view <KEY> --plain` (`--comments 10` for discussion). `jira issue view` only supports `--plain`, `--comments`, and `--raw`; it has no `--no-truncate` (that flag is on `jira issue list`). The `--plain` header wraps long lines, so a multi-valued field (components, labels, fix versions) reads as a different number of values than it has: never take such a field from the header, read it from `--raw`.
- Raw fields (parent, links, all fields): `jira issue view <KEY> --raw`. Read the JSON directly, or pull one field with an anchored `jq` path (`jira issue view <KEY> --raw | jq '.fields.components[] | {id, name}'`); never pipe it into `python3 -c`, `node -e`, or any interpreter. Inline-code execution is arbitrary code and is correctly blocked; use the CLI's own flags plus `jq`.
- **Never `grep` a loose field name over the raw JSON.** Every issue link embeds a nested issue object carrying its own `key`, `summary`, `status`, `priority` and `issuetype`, so a `grep` for `"name"`, `"id"`, `issuetype` or `status` returns a *linked* ticket's values while looking like the root's, and the answer changes with the link order. A `jq` path is anchored at the root and cannot drift into a link. Same for the link vocabulary: read it from a real ticket (`jq '[.fields.issuelinks[].type | {name, inward, outward}] | unique'`) rather than guessing the type names.
- Epic children: `jira epic list <EPIC-KEY> --plain`. Children of a parent: `jira issue list -P <PARENT-KEY> --plain --no-truncate`.
- PR: `gh pr view <n> --repo <owner>/<repo> --json ...`. PRs by key: `gh pr list --repo <owner>/<repo> --search "<KEY>" --state all --json ...`.

## Reading repos not cloned locally

Per the Playbook's "Never fabricate" rule, when context lives in another repo, do not guess: read it remotely with `gh`, no clone needed.

- A file's contents: `gh api repos/<owner>/<repo>/contents/<path> --jq '.content' | base64 -d` (or `gh api .../contents/<path>?ref=<branch>`).
- List a directory: `gh api repos/<owner>/<repo>/contents/<dir>`.
- Search code across a repo or org: `gh search code "<query>" --repo <owner>/<repo>` (or `--owner <org>`).
- A PR's changed files and diff: read the pushed PR head, which is what a review must read. **First, check whether the branch is already checked out locally at that head** (Playbook "read local state before re-fetching remote"): compare `gh pr view <n> --json headRefOid` against `git -C <clone> rev-parse HEAD`. If they match, read the diff straight from the working tree (`git -C <clone> diff <base>...HEAD`, or read the changed files directly), no fetch, no checkout. This is the fastest path and the one to prefer when the user already has the branch ready; do not re-fetch what is already local at the head. **Otherwise, prefer the local clone whenever the repo is cloned** (faster than paging the whole PR over the API; most of the user's repos are cloned under the projects root, memory `projects-root`, one level deep). Get the head into the clone read-only, without a checkout and without touching the user's current branch:
  1. `git -C <clone> fetch origin pull/<n>/head` (auto-approved deterministically: the Bash gate's fast path treats `git fetch` as local-reversible and skips the leading `-C <clone>`, so any form is approved without a model call; the `git fetch *` allow rule alone does not cover this, since this form leads with `git -C`).
  2. List changed files: `git -C <clone> diff --name-only origin/<base>...FETCH_HEAD` (base is the PR's `baseRefName`), or the full diff `git -C <clone> diff origin/<base>...FETCH_HEAD`.
  3. Read a changed file in full at the PR head: `git -C <clone> show FETCH_HEAD:<path>`.
  This reads the exact pushed head with no working-tree change, so it is safe even mid-review and needs no clean tree (nothing is checked out).
- Only go remote (`gh`) when the repo is genuinely not cloned: `gh pr diff <n> --repo <owner>/<repo>`. If the diff could be large, do not dump it whole into context: measure it first with a pipe (`gh pr diff <n> --repo <owner>/<repo> | wc -l`), then if it is big read the changed files (`gh pr view <n> --json files`) one at a time rather than the whole diff. Measure with a pipe, not a redirect to a file: `> /tmp/<file>` makes the command prompt for permission, a plain pipe does not.

## Using the context

Treat the ticket plus its chain as the source of truth per the Playbook: work type, acceptance criteria, scope, and the rationale behind them. Do not invent acceptance criteria. If anything is thin or ambiguous, surface it to the user rather than guessing.

The ticket and epic are authoritative for *what the work is*, not for concrete facts the repo itself defines. A Jira ticket or epic states intent, and its wording can be aspirational or stale (an epic titled "The Bi-Weekly Review" for a process the repo's README documents as weekly). So for any concrete operational fact the task quotes (a cadence, threshold, owner, channel, name, metric, widget title), find the repo artifact that defines it (README, config, code, terraform, the same file the deliverable will link to) and take the value from there, do not lift it from the ticket or epic. This is the same rule as the map's runtime line, generalized: the source that *defines* a fact outranks a source that merely *mentions* it. If they differ, the repo wins and you name the conflict rather than resolving it silently (Playbook).

## Read-only boundary

Per the Playbook's "Read-only by default for external tools" rule, this skill only reads. It may read issue, epic, PR, and repo content, and may inspect CI (`gh run view/list`, `gh pr checks`, workflow logs). No state changes: no `jira issue create`/transitions/comments/edits; no `gh pr create`/merge/review/comment/close; no triggering, re-running, or toggling workflows. A state-changing action must be requested explicitly, as a separate step outside this skill.
