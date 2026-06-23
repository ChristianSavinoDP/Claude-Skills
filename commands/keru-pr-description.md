---
description: Write a PR description following the Playbook and repo template (invokes the pr-description skill).
---

Write the PR description for: $ARGUMENTS

This usually runs BEFORE the PR exists, to describe work already done on the current branch. Default to that: do not look for an existing PR. Get the work from the local branch (`git diff` against the base) and the Jira ticket and chain (for the JIRA link and acceptance criteria) via the `gather-context` skill, then use the `pr-description` skill.

Only if `$ARGUMENTS` contains a GitHub PR link/number, read that PR instead (its diff and branch) to update its description. If you lack the ticket or acceptance criteria, ask for the ticket; do not ask for a PR.
