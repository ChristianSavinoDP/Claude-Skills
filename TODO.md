# TODO / Ideas

A running list of ideas for this repo. Add new ones at the top of the list.

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

**Decisions:**

- Output: classify each item as either a routine dependency update or a security issue, so the user can tell them apart at a glance and prioritize the security ones.
- Scope: read-only by default. Never auto-merge: merging is always a human action, no exceptions. The most the user can opt into per run is auto-approving a PR whose checks are green; the merge itself stays with the user. Gate even that on the repo's own permission config: `gh pr review` / `gh pr merge` currently sit in the `ask` list (`config/permissions.json`) and the Bash safety-judge hook treats them as remote mutations, so auto-approve is NOT allowed today. Until that permission is explicitly granted, the agent stays read-only.
